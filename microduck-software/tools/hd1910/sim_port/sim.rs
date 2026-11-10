//! A [`RobotIo`] whose robot is in MuJoCo.
//!
//! **The seam is the one place a simulator is allowed to exist.** Everything above this trait —
//! the 50 Hz control loop, the policy, [`crate::safety::Safety`], fall detection, odometry,
//! kinematics, every IPC call and `robotctl` — runs unchanged and cannot tell the difference.
//!
//! ## Where this came from, and what was changed
//!
//! Ported from `ft1910/duck-control/src/sim.rs` (the pollen line), which is the only
//! implementation of the `RemoteIo` protocol that exists. The wire protocol is **not** ours to
//! define: it is whatever `mjlab_microduck/sim/body_server.py` answers, and that is
//! `PROTOCOL = 1` with ops `hello`, `read`, `write`, `gain`, `torque`, `slow` (and `tof`, which
//! this trait has no method for).
//!
//! Three deltas, all forced by this crate's trait rather than chosen:
//!
//! 1. **No `measures_load` / `measures_velocity`.** This line's [`RobotIo`] has neither;
//!    [`Sensors`] is fixed-size arrays throughout, so "nothing measured this" and "measured
//!    zero" are the same value here. The upstream file's per-frame `load_reported` flag has no
//!    consumer on this trait and is dropped rather than kept as dead state.
//! 2. **No `reboot`.** A simulated servo has no latched hardware error, and this trait has no
//!    reboot to implement (`ft1910` added one for protocol-2 Dynamixels).
//! 3. **`set_limp` is left at the trait's default**, which reports `IoError::Bus`. The
//!    simulator has no per-joint limp op: `body_server.py` only knows whole-robot `torque`.
//!    Rest poses that call it will log a bus error under `--sim` instead of quietly claiming
//!    to have unloaded joints. See `docs/active/` for the note; this is a known gap, not an
//!    oversight.
//!
//! ## Why TCP and not a unix socket
//!
//! A unix path is capped at `SUN_LEN` — about 108 bytes — which a scratch directory blows
//! through immediately, and a socket path does not cross from a Windows host to the simulator
//! (or out of a container) the way a port does. This project runs the daemon on Windows, where
//! there is no `UnixListener` at all.
//!
//! ## Why JSON
//!
//! One tick is fifteen joints in and fifteen out — about a kilobyte, so 50 KB/s at 50 Hz, which
//! is nothing next to being able to read a frame with `nc` and write the other half of it in
//! twenty lines of Python. The alternative is a packed struct shared between two repositories in
//! two languages, which is the shape of thing this project has already lost days to when an
//! offset was wrong and the failure was silent.
//!
//! ## What it does when the simulator goes away
//!
//! It goes away *often*: MuJoCo compiles its model, so changing the number of ducks means
//! restarting it, and the ducks are expected to survive that. So a dead connection is an error
//! returned to the caller and a reconnect on the next call — no backoff thread, because **the
//! control loop is the retry timer**. `robotd` already treats a failed `read` as a tick to skip
//! rather than a reason to exit.

use std::io::{BufRead, BufReader, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::imu::ImuData;
use crate::io::{IoError, JointTargets, Result, RobotIo, Sensors, SlowSensors};
use crate::model::NUM_JOINTS;

/// Bumped when the wire format changes in a way an older peer would misread.
///
/// Checked in the handshake and reported by *both* numbers when it fails, because the two halves
/// live in two repositories and "the simulator is too old" and "the daemon is too old" are the
/// same symptom otherwise. `body_server.py:59` is the other half of this constant.
pub const PROTOCOL: u32 = 1;

/// How long to wait for the simulator to answer one request.
///
/// Comfortably longer than a tick, because a simulator that has just been asked to step a
/// contact-heavy scene can be late without being broken — and comfortably shorter than forever,
/// because a wedged simulator must not wedge the control loop with it.
const TIMEOUT: Duration = Duration::from_millis(200);

/// One request. `op` is the tag, so a frame is readable in a log without a decoder.
#[derive(Debug, Serialize)]
#[serde(tag = "op")]
enum Request<'a> {
    #[serde(rename = "hello")]
    Hello { protocol: u32, joints: usize },
    #[serde(rename = "read")]
    Read,
    #[serde(rename = "write")]
    Write { targets: &'a [f64; NUM_JOINTS] },
    #[serde(rename = "gain")]
    Gain { kp: u16 },
    #[serde(rename = "torque")]
    Torque { on: bool },
    #[serde(rename = "slow")]
    Slow,
}

#[derive(Debug, Deserialize)]
struct Hello {
    protocol: u32,
}

/// What the simulator reports, in exactly the units [`Sensors`] wants — radians, rad/s, mA, and
/// the IMU already resolved into the trunk frame.
///
/// **The simulator does the conversion, not this.** MuJoCo knows its own model's joint order,
/// scaling and frame; a translation layer here would be a second place for that knowledge to live
/// and drift. What crosses the wire is the robot's own units.
///
/// Extra keys the simulator volunteers — `trunk_z`, `trunk`, `sim_time` — are ignored: `serde`
/// drops what the struct does not name, and they exist for tooling that asks "did it stand up?",
/// which no robot can answer about itself.
#[derive(Debug, Deserialize)]
struct SensorFrame {
    positions: [f64; NUM_JOINTS],
    velocities: [f64; NUM_JOINTS],
    /// The simulator always sends this (`body_server.py` derives it from actuator force). Kept
    /// `Option` anyway so a model that has no actuator force to report still parses — and then
    /// the zeros it defaults to are indistinguishable from a measurement, which is a property of
    /// [`Sensors`] on this line rather than a choice made here.
    #[serde(default)]
    currents_ma: Option<[f64; NUM_JOINTS]>,
    imu: ImuFrame,
}

#[derive(Debug, Deserialize)]
struct ImuFrame {
    gyro: [f64; 3],
    gravity: [f64; 3],
    quat: [f64; 4],
}

#[derive(Debug, Deserialize)]
struct SlowFrame {
    volts: f64,
    temps_c: [f64; NUM_JOINTS],
}

/// An acknowledgement, so a write that the simulator refused is not silently a write that worked.
#[derive(Debug, Deserialize)]
struct Ack {
    #[serde(default)]
    error: Option<String>,
}

/// A robot in MuJoCo, reached over TCP.
pub struct RemoteIo {
    addr: String,
    link: Option<Link>,
    /// Reported once rather than every tick a disconnected loop runs.
    complained: bool,
    /// Whether to assert the torque state on every fresh connection. See [`Self::at_powered`].
    powered: bool,
    /// The last torque state this client asked for, re-applied after a simulator restart.
    /// `None` until someone says otherwise, in which case a powered client assumes `on`.
    torque: Option<bool>,
}

struct Link {
    write: TcpStream,
    read: BufReader<TcpStream>,
}

impl RemoteIo {
    /// Name the simulator. Nothing is connected until the first call — a daemon must start
    /// whether or not the simulator is up yet, exactly as it starts without a robot on the bus.
    pub fn at(addr: impl Into<String>) -> Self {
        Self {
            addr: addr.into(),
            link: None,
            complained: false,
            powered: false,
            torque: None,
        }
    }

    /// The same client, but for a daemon running a **real** robot against this simulator.
    ///
    /// Real servos have torque from the moment the board is powered; `robotd` never sends
    /// `torque on` at startup and only does so when a human enables a limp robot, because a
    /// process starting must not change what the joints are doing. `body_server.py` differs:
    /// it holds an unclaimed duck still (`World.step` calls `restore()` every physics step)
    /// until something sends `torque on`, which clears its `released` flag. Without this,
    /// a mode switch arriving before `robot.enable` moves `bringup` straight to `Ready` and
    /// the policy computes against a body that is pinned in place — inference runs, joints
    /// never move, and nothing reports an error.
    ///
    /// So a powered client declares torque on the first handshake, matching the hardware the
    /// rest of the daemon was written for. It also remembers the last state it was asked for
    /// and re-applies it after a reconnect: a daemon that issued `relax` must not have torque
    /// silently restored just because MuJoCo restarted.
    ///
    /// `set_torque(on)` also resets the simulator's `ctrl` to its current `qpos`, so releasing
    /// a duck that booted in the `SIT` keyframe cannot yank it towards the standing pose.
    pub fn at_powered(addr: impl Into<String>) -> Self {
        Self {
            powered: true,
            ..Self::at(addr)
        }
    }

    fn connect(&mut self) -> Result<&mut Link> {
        if self.link.is_none() {
            let address = self
                .addr
                .to_socket_addrs()
                .and_then(|mut a| {
                    a.next()
                        .ok_or_else(|| std::io::Error::other("resolved to no address"))
                })
                .map_err(|source| IoError::Port {
                    path: self.addr.clone(),
                    source,
                })?;

            // A connect timeout as well as a read one: a port nobody listens on refuses
            // instantly, but a host that silently drops packets would otherwise hang the loop.
            let stream =
                TcpStream::connect_timeout(&address, TIMEOUT).map_err(|source| IoError::Port {
                    path: self.addr.clone(),
                    source,
                })?;

            // **Nagle would be catastrophic here and silent.** It delays a small write waiting
            // for more to send, up to ~40 ms — twice the tick — turning every transaction into a
            // missed deadline that looks like a slow simulator.
            let _ = stream.set_nodelay(true);
            let _ = stream.set_read_timeout(Some(TIMEOUT));
            let _ = stream.set_write_timeout(Some(TIMEOUT));

            let read = BufReader::new(stream.try_clone().map_err(|source| IoError::Port {
                path: self.addr.clone(),
                source,
            })?);
            let mut link = Link {
                write: stream,
                read,
            };

            let hello: Hello = exchange(
                &mut link,
                &Request::Hello {
                    protocol: PROTOCOL,
                    joints: NUM_JOINTS,
                },
            )?;
            if hello.protocol != PROTOCOL {
                return Err(IoError::Bus(format!(
                    "the simulator speaks protocol {} and this daemon speaks {PROTOCOL} — one of \
                     the two is out of date, and they are in different repositories",
                    hello.protocol
                )));
            }

            if self.powered {
                // Not a policy decision, and not an `enable`: the real bus has torque from
                // power-on, and everything above this trait is written for that. The simulator
                // needs to be told once per connection, because a MuJoCo restart builds a fresh
                // `Body` whose `released` flag is false again. `torque` remembers a `relax` that
                // happened before the restart; without it, reconnecting would power a robot a
                // human just told to go limp.
                let on = self.torque.unwrap_or(true);
                let ack: Ack = exchange(&mut link, &Request::Torque { on })?;
                acked(ack, "the power-on torque state")?;
                tracing::info!(on, "simulated body torque state declared");
            }

            tracing::info!(addr = %self.addr, protocol = PROTOCOL, "simulated body");
            self.complained = false;
            self.link = Some(link);
        }
        Ok(self.link.as_mut().expect("just connected"))
    }

    /// One request and its answer, dropping the connection if anything about it fails.
    ///
    /// Dropping on *any* error, not only on a closed socket: a frame that will not parse means
    /// the two ends disagree about where a message begins, and there is no way to resynchronise
    /// a line protocol except by starting again.
    fn call<T: for<'de> Deserialize<'de>>(&mut self, request: &Request<'_>) -> Result<T> {
        let result = self.connect().and_then(|link| exchange(link, request));
        if let Err(error) = &result {
            self.link = None;
            if !self.complained {
                self.complained = true;
                tracing::warn!(
                    addr = %self.addr, %error,
                    "no simulated body; retrying every tick until it answers"
                );
            }
        }
        result
    }
}

fn exchange<T: for<'de> Deserialize<'de>>(link: &mut Link, request: &Request<'_>) -> Result<T> {
    let mut line = serde_json::to_string(request).map_err(|e| IoError::Bus(e.to_string()))?;
    line.push('\n');
    link.write
        .write_all(line.as_bytes())
        .map_err(|e| IoError::Bus(format!("sending {}: {e}", tag(request))))?;

    let mut answer = String::new();
    let read = link
        .read
        .read_line(&mut answer)
        .map_err(|e| IoError::Bus(format!("waiting for {}: {e}", tag(request))))?;
    if read == 0 {
        return Err(IoError::Bus(format!(
            "the simulator closed the connection during {}",
            tag(request)
        )));
    }
    serde_json::from_str(&answer).map_err(|e| {
        IoError::Bus(format!(
            "{} answered with something this cannot read: {e}",
            tag(request)
        ))
    })
}

fn tag(request: &Request<'_>) -> &'static str {
    match request {
        Request::Hello { .. } => "hello",
        Request::Read => "read",
        Request::Write { .. } => "write",
        Request::Gain { .. } => "gain",
        Request::Torque { .. } => "torque",
        Request::Slow => "slow",
    }
}

fn acked(ack: Ack, what: &str) -> Result<()> {
    match ack.error {
        None => Ok(()),
        Some(why) => Err(IoError::Bus(format!("the simulator refused {what}: {why}"))),
    }
}

impl RobotIo for RemoteIo {
    fn read(&mut self) -> Result<Sensors> {
        let frame: SensorFrame = self.call(&Request::Read)?;
        Ok(Sensors {
            positions: frame.positions,
            velocities: frame.velocities,
            currents_ma: frame.currents_ma.unwrap_or([0.0; NUM_JOINTS]),
            imu: ImuData {
                gyro: frame.imu.gyro,
                gravity: frame.imu.gravity,
                quat: frame.imu.quat,
            },
        })
    }

    fn write(&mut self, targets: &JointTargets) -> Result<()> {
        let ack: Ack = self.call(&Request::Write {
            targets: &targets.positions,
        })?;
        acked(ack, "the joint targets")
    }

    fn set_gain(&mut self, kp: u16) -> Result<()> {
        let ack: Ack = self.call(&Request::Gain { kp })?;
        acked(ack, "the position gain")
    }

    fn set_torque(&mut self, on: bool) -> Result<()> {
        let ack: Ack = self.call(&Request::Torque { on })?;
        acked(ack, if on { "torque on" } else { "torque off" })?;
        // Only a successful write becomes the state to re-apply after a reconnect. A refused
        // `relax` must leave the robot powered, not have the next simulator restart finish it.
        self.torque = Some(on);
        Ok(())
    }

    fn slow_sensors(&mut self) -> Result<SlowSensors> {
        let frame: SlowFrame = self.call(&Request::Slow)?;
        Ok(SlowSensors {
            volts: frame.volts,
            temps_c: frame.temps_c,
        })
    }

    // `set_limp`, `imu_stale` and `imu_ready` are deliberately left at the trait's defaults:
    // the simulator has no per-joint limp op, no bus to report stale IMU blocks from, and its
    // orientation is exact from the first frame, so there is nothing to declare.
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    /// A simulator made of canned answers: one script per connection, one answer per request.
    ///
    /// A real socket rather than a trait behind the socket, because the things worth testing here
    /// *are* the socket — a peer that hangs up, a frame that will not parse, a second connection
    /// after the first died.
    fn simulator(scripts: Vec<Vec<&'static str>>) -> (String, thread::JoinHandle<Vec<String>>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("a loopback port");
        let addr = listener.local_addr().expect("its address").to_string();
        let handle = thread::spawn(move || {
            let mut heard = Vec::new();
            for script in scripts {
                let (stream, _) = listener.accept().expect("a connection");
                let mut out = stream.try_clone().expect("a writer");
                let mut lines = BufReader::new(stream);
                for reply in script {
                    let mut line = String::new();
                    if lines.read_line(&mut line).expect("a request") == 0 {
                        break;
                    }
                    heard.push(line.trim().to_string());
                    out.write_all(reply.as_bytes()).expect("a reply");
                    out.write_all(b"\n").expect("a newline");
                }
            }
            heard
        });
        (addr, handle)
    }

    const HELLO: &str = r#"{"protocol":1}"#;
    // One line, because the protocol is one frame per line and a test fixture that wraps would be
    // testing the fixture.
    const SENSORS: &str = concat!(
        r#"{"positions":[0.1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"#,
        r#""velocities":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.5],"#,
        r#""currents_ma":[10,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"#,
        r#""trunk_z":0.125,"sim_time":1.5,"#,
        r#""imu":{"gyro":[0,0,0],"gravity":[0,0,-1],"quat":[1,0,0,0]}}"#
    );
    const OK: &str = r#"{}"#;

    #[test]
    fn a_read_carries_the_sensors_the_loop_expects() {
        let (addr, sim) = simulator(vec![vec![HELLO, SENSORS]]);
        let mut io = RemoteIo::at(addr);
        let sensors = io.read().expect("a sensor frame");
        assert_eq!(sensors.positions[0], 0.1);
        assert_eq!(sensors.velocities[NUM_JOINTS - 1], 0.5);
        assert_eq!(sensors.currents_ma[0], 10.0);
        assert_eq!(sensors.imu.gravity, [0.0, 0.0, -1.0]);

        let heard = sim.join().expect("the simulator thread");
        assert!(heard[0].contains(r#""op":"hello""#), "{heard:?}");
        assert!(heard[1].contains(r#""op":"read""#), "{heard:?}");
    }

    /// The simulator volunteers keys this struct does not name — `trunk_z`, `trunk`,
    /// `sim_time`. They must not make a frame unreadable: a daemon that dropped the connection
    /// over an extra key would work against one body_server and fail against the next.
    #[test]
    fn keys_the_struct_does_not_name_are_ignored() {
        const EXTRA: &str = concat!(
            r#"{"positions":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"#,
            r#""velocities":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"#,
            r#""currents_ma":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"#,
            r#""trunk_z":0.125,"trunk":[1,2,0.125],"sim_time":9.5,"#,
            r#""imu":{"gyro":[0,0,0],"gravity":[0,0,-1],"quat":[1,0,0,0]}}"#
        );
        let (addr, sim) = simulator(vec![vec![HELLO, EXTRA]]);
        let mut io = RemoteIo::at(addr);
        io.read().expect("a frame with keys this does not know");
        sim.join().expect("the simulator thread");
    }

    /// A frame with no load block still parses, and the zeros it defaults to are what a consumer
    /// sees — a property of this line's [`Sensors`], which cannot say "not measured". Asserted so
    /// the behaviour is stated rather than discovered.
    #[test]
    fn a_frame_without_a_load_block_defaults_to_zero_rather_than_failing() {
        const NO_LOAD: &str = concat!(
            r#"{"positions":[0.1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"#,
            r#""velocities":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.5],"#,
            r#""imu":{"gyro":[0,0,0],"gravity":[0,0,-1],"quat":[1,0,0,0]}}"#
        );
        let (addr, sim) = simulator(vec![vec![HELLO, NO_LOAD]]);
        let mut io = RemoteIo::at(addr);
        let sensors = io.read().expect("a frame with no load block");
        assert_eq!(sensors.currents_ma, [0.0; NUM_JOINTS]);
        sim.join().expect("the simulator thread");
    }

    #[test]
    fn the_targets_cross_in_joint_order() {
        let (addr, sim) = simulator(vec![vec![HELLO, OK]]);
        let mut io = RemoteIo::at(addr);
        let mut positions = [0.0; NUM_JOINTS];
        positions[2] = -0.4579;
        io.write(&JointTargets::new(positions)).expect("a write");

        let heard = sim.join().expect("the simulator thread");
        // Positional, exactly as the wire everywhere else in this project is: the third number is
        // the third joint, and nothing names it.
        assert!(heard[1].contains("[0.0,0.0,-0.4579,"), "{heard:?}");
    }

    #[test]
    fn a_protocol_mismatch_names_both_versions() {
        let (addr, _sim) = simulator(vec![vec![r#"{"protocol":99}"#]]);
        let mut io = RemoteIo::at(addr);
        let error = io
            .read()
            .expect_err("a mismatch is fatal to the connection");
        let said = error.to_string();
        assert!(said.contains("99") && said.contains("1"), "{said}");
        assert!(said.contains("different repositories"), "{said}");
    }

    #[test]
    fn a_refusal_is_an_error_rather_than_a_silent_success() {
        let (addr, _sim) = simulator(vec![vec![HELLO, r#"{"error":"torque is disabled"}"#]]);
        let mut io = RemoteIo::at(addr);
        let error = io
            .set_torque(true)
            .expect_err("a refusal must not read as done");
        assert!(error.to_string().contains("torque is disabled"), "{error}");
    }

    /// The gap this line has and `ft1910` does not: the simulator has no per-joint limp op, so
    /// the default trait implementation refuses. Asserted so a rest pose under `--sim` reports a
    /// bus error instead of quietly believing it unloaded a joint.
    #[test]
    fn set_limp_reports_that_the_simulator_cannot_do_it() {
        let mut io = RemoteIo::at("127.0.0.1:1");
        let error = io
            .set_limp([true; NUM_JOINTS])
            .expect_err("no limp op on the wire");
        assert!(error.to_string().contains("limp"), "{error}");
    }

    #[test]
    fn a_simulator_that_restarts_is_reconnected_to_on_the_next_tick() {
        // The case this exists for: MuJoCo compiles its model, so changing the number of ducks
        // restarts it — and the ducks are expected to survive that. The first connection dies
        // mid-read; the second is expected to be made without anyone asking.
        let (addr, sim) = simulator(vec![vec![HELLO], vec![HELLO, SENSORS]]);
        let mut io = RemoteIo::at(addr);

        io.read().expect_err("the simulator hung up");
        let sensors = io.read().expect("reconnected on the next call");
        assert_eq!(sensors.positions[0], 0.1);

        let heard = sim.join().expect("the simulator thread");
        let hellos = heard.iter().filter(|l| l.contains("hello")).count();
        assert_eq!(
            hellos, 2,
            "the second connection must handshake again: {heard:?}"
        );
    }

    #[test]
    fn a_frame_that_will_not_parse_drops_the_connection() {
        // Not merely an error: a half-read line means the two ends disagree about where a message
        // starts, and a line protocol cannot resynchronise except by starting again.
        let (addr, sim) = simulator(vec![vec![HELLO, "not json"], vec![HELLO, SENSORS]]);
        let mut io = RemoteIo::at(addr);
        io.read().expect_err("garbage is an error");
        io.read().expect("a fresh connection, not a wedged one");

        let heard = sim.join().expect("the simulator thread");
        assert_eq!(heard.iter().filter(|l| l.contains("hello")).count(), 2);
    }

    /// Why this exists: `robotd` never sends `torque on` at startup (a process starting must
    /// not change what the joints are doing), but `body_server.py` pins an unclaimed duck in
    /// place until it sees that frame. A `setMode` before `enable` moves `bringup` to `Ready`
    /// without ever powering the joints, so the policy computes against a frozen body.
    #[test]
    fn a_powered_client_declares_torque_on_right_after_the_handshake() {
        let (addr, sim) = simulator(vec![vec![HELLO, OK, SENSORS]]);
        let mut io = RemoteIo::at_powered(addr);
        io.read().expect("a sensor frame from a released body");

        let heard = sim.join().expect("the simulator thread");
        assert_eq!(heard.len(), 3, "{heard:?}");
        assert!(heard[0].contains(r#""op":"hello""#), "{heard:?}");
        assert!(heard[1].contains(r#""op":"torque""#), "{heard:?}");
        assert!(heard[1].contains(r#""on":true"#), "{heard:?}");
        assert!(heard[2].contains(r#""op":"read""#), "{heard:?}");
    }

    /// Negative control for the switch: the plain client used by the protocol tests and by
    /// `sim_e2e.rs` must stay a pure protocol client. If this ever sees a torque frame,
    /// `at_powered` is not what is doing the work and the test above proves nothing.
    #[test]
    fn an_unpowered_client_sends_no_torque_frame_at_all() {
        let (addr, sim) = simulator(vec![vec![HELLO, SENSORS]]);
        let mut io = RemoteIo::at(addr);
        io.read().expect("a sensor frame");

        let heard = sim.join().expect("the simulator thread");
        assert_eq!(heard.len(), 2, "{heard:?}");
        assert!(
            !heard.iter().any(|l| l.contains("torque")),
            "a plain client changed the torque state: {heard:?}"
        );
    }

    /// A `relax` must survive a MuJoCo restart. Re-applying `on` blindly would silently power
    /// a robot a human just told to go limp — the exact safety invariant `robotd` documents.
    #[test]
    fn a_relax_is_reapplied_after_the_simulator_restarts() {
        // Connection 1: hello, boot torque, the relax, then the simulator hangs up on a read.
        // Connection 2: hello, the *remembered* torque state, then the sensor frame.
        let (addr, sim) = simulator(vec![
            vec![HELLO, OK, OK],
            vec![HELLO, OK, SENSORS],
        ]);
        let mut io = RemoteIo::at_powered(addr);

        io.set_torque(false).expect("relax acknowledged");
        io.read().expect_err("the simulator hung up");
        io.read().expect("reconnected on the next call");

        let heard = sim.join().expect("the simulator thread");
        let torques: Vec<&String> = heard.iter().filter(|l| l.contains("torque")).collect();
        assert_eq!(torques.len(), 3, "{heard:?}");
        assert!(torques[0].contains(r#""on":true"#), "{torques:?}");
        assert!(torques[1].contains(r#""on":false"#), "{torques:?}");
        assert!(
            torques[2].contains(r#""on":false"#),
            "the restart silently restored torque: {torques:?}"
        );
    }

    /// A simulator that refuses the declaration is a failed connection, not a robot that is
    /// quietly believed to be released.
    #[test]
    fn a_refused_power_on_torque_is_an_error() {
        let (addr, _sim) = simulator(vec![vec![HELLO, r#"{"error":"torque unavailable"}"#]]);
        let mut io = RemoteIo::at_powered(addr);
        let error = io.read().expect_err("a refused declaration is fatal to the connection");
        assert!(error.to_string().contains("torque unavailable"), "{error}");
    }
}
