//! Live-wire test: the *real* `mjlab_microduck/sim/body_server.py` on the other end of the TCP
//! line, not a canned-answer socket.
//!
//! `src/sim.rs`'s own tests prove the client's logic against a scripted peer. They cannot prove
//! that a frame produced by Python's `json.dumps` — extra keys, Python float spellings, its
//! newline — is the frame this struct actually parsed, nor what one tick costs against a real
//! MuJoCo step. This file closes that gap.
//!
//! Deliberately `#[ignore]`: it needs a simulator process this crate cannot start. Run it with
//! `tools/hd1910/sim_e2e_check.py`, which starts the server, runs this, then runs it again with
//! the server **down** and requires that second run to fail. A green result therefore cannot be
//! a test that never connected to anything.

use duck_control::io::{JointTargets, RobotIo};
use duck_control::model::NUM_JOINTS;
use duck_control::sim::RemoteIo;
use std::env;
use std::time::{Duration, Instant};

const TICKS: usize = 50;
const WAIT: Duration = Duration::from_millis(300);

fn addr() -> String {
    env::var("SIM_ADDR").unwrap_or_else(|_| "127.0.0.1:7801".to_string())
}

fn norm(v: &[f64]) -> f64 {
    v.iter().map(|x| x * x).sum::<f64>().sqrt()
}

/// All six ops against a live simulator, with checks that a frame of plausible-looking zeros
/// would fail: the IMU must be a real unit vector, the slow sensors must be the constants the
/// server actually publishes, and each command must be acknowledged rather than merely sent.
#[test]
#[ignore = "needs a live body_server.py; use tools/hd1910/sim_e2e_check.py"]
fn every_op_against_the_real_simulator() {
    let mut io = RemoteIo::at(addr());

    // `hello` is lazy: the handshake happens inside this first read.
    let s = io.read().expect("hello + read against the real simulator");
    assert!(
        s.positions.iter().all(|x| x.is_finite())
            && s.velocities.iter().all(|x| x.is_finite())
            && s.currents_ma.iter().all(|x| x.is_finite()),
        "non-finite sensor value"
    );
    // A gravity vector that is not unit length is exactly the kind of silent bug that a
    // "looks reasonable" assertion misses: the policy and fall detection both threshold on it.
    assert!(
        (norm(&s.imu.gravity) - 1.0).abs() < 1e-3,
        "gravity is not a unit vector: {:?}",
        s.imu.gravity
    );
    assert!(
        (norm(&s.imu.quat) - 1.0).abs() < 1e-3,
        "quat is not normalized: {:?}",
        s.imu.quat
    );
    println!(
        "read: pos0={:.6} vel0={:.6} cur0={:.6} |g|={:.6} |q|={:.6} gravity={:?}",
        s.positions[0],
        s.velocities[0],
        s.currents_ma[0],
        norm(&s.imu.gravity),
        norm(&s.imu.quat),
        s.imu.gravity
    );

    let slow = io.slow_sensors().expect("slow frame from the real simulator");
    assert_eq!(slow.volts, 7.4, "volts differs from body_server NOMINAL_VOLTS");
    assert!(
        slow.temps_c.iter().all(|&t| t == 32.0) && slow.temps_c.len() == NUM_JOINTS,
        "temps differ from NOMINAL_TEMP_C: {:?}",
        slow.temps_c
    );
    println!("slow: volts={} temps[0]={} count={}", slow.volts, slow.temps_c[0], slow.temps_c.len());

    // Torque on before commanding anything; a duck with its motors off cannot move.
    io.set_torque(true).expect("torque on acknowledged");
    io.set_gain(8).expect("gain acknowledged");

    let mut targets = s.positions;
    io.write(&JointTargets::new(targets))
        .expect("write acknowledged");
    targets[2] += 0.01;
    io.write(&JointTargets::new(targets))
        .expect("a second write acknowledged");

    // One tick is one request/answer. Timing this on the real peer is the only way to see a
    // Nagle regression (~40 ms) or a simulator that cannot keep up with 50 Hz.
    let mut times = Vec::with_capacity(TICKS);
    for _ in 0..TICKS {
        let started = Instant::now();
        let frame = io.read().expect("a tick against the live simulator");
        assert!(frame.positions.iter().all(|x| x.is_finite()));
        times.push(started.elapsed());
    }
    times.sort();
    let p50 = times[TICKS / 2];
    let max = times[TICKS - 1];
    println!("read RTT over {TICKS} live ticks: p50={p50:?} max={max:?}");
    assert!(
        p50 < Duration::from_millis(10),
        "p50 {p50:?} smells like Nagle or a stalled simulator"
    );
    assert!(
        max < Duration::from_millis(200),
        "max {max:?} reached the client's 200 ms timeout"
    );

    io.set_torque(false).expect("torque off acknowledged");
    println!("all six ops acknowledged against the live simulator");
}

/// The Python-side protocol test in `docs/active/` showed a write really moves a joint, but
/// measured it with a hand-written frame. Here the same question goes through `sim.rs` itself,
/// with an uncommanded window measured first so the assertion is against the server's own drift
/// rather than against zero.
#[test]
#[ignore = "needs a live body_server.py; use tools/hd1910/sim_e2e_check.py"]
fn a_write_moves_the_simulated_joint_toward_its_target() {
    let mut io = RemoteIo::at(addr());
    io.set_torque(true).expect("torque on");

    let base = io.read().expect("read").positions[2];
    std::thread::sleep(WAIT);
    let drifted = io.read().expect("read").positions[2];
    let drift = drifted - base;

    // Command *all* joints to where they already are, with one offset. Writing zeros for the
    // other fourteen would collapse the duck and make this a test of falling over.
    let mut targets = io.read().expect("read").positions;
    let before = targets[2];
    let goal = before + 0.20;
    targets[2] = goal;
    io.write(&JointTargets::new(targets)).expect("write");
    std::thread::sleep(WAIT);
    let after = io.read().expect("read").positions[2];
    let moved = after - before;

    println!(
        "joint 2: uncommanded 300ms drift={drift:+.6} | commanded +0.20 -> before={before:.6} after={after:.6} delta={moved:+.6}"
    );
    // Direction is the hard check; magnitude is compared to the drift measured in the very same
    // run, so a server whose physics happens to be stiffer elsewhere still passes.
    assert!(
        moved > 0.0,
        "the joint moved away from its target (drift was {drift:+.6})"
    );
    assert!(
        moved > drift.abs().max(1e-4) * 2.0,
        "delta {moved:+.6} is not distinguishable from uncommanded drift {drift:+.6}"
    );
    io.set_torque(false).expect("torque off");
}
