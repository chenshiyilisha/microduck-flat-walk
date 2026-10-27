# SPDX-License-Identifier: Apache-2.0
"""Register the two candidate servos with BAM so `load_model(json_file=...)` accepts them.

Why this file exists
--------------------
`bam.model.load_model_from_dict` looks the actuator up by name in
`bam.actuators.actuators`, and that table only carries Dynamixel, STS3215, eRob and
Unitree Go1. Both of our candidate servos are unregistered, so a params JSON whose
`"actuator"` is `hl2915` or `hd1910` raises `KeyError` before any physics runs.

The HL-2915 class is DuckBuddy's, copied verbatim from
`training/bam/hl2915.py` (Apache-2.0) because their fit was produced against it --
using a different class here would silently change the control law under the numbers.
The HD-1910 class is the same shape with the values from OpenMicroDuck's
`hd1910_characterization.json` (2026-09-10, 72 pendulum runs).

What each simulator relies on
----------------------------
`vin`        supply voltage the firmware sees. HD-1910's identification ran at 5.0 V;
             kt and R are motor constants and do not move with vin, so running the
             model at 7.4 V only changes vin.
`kp`         the servo's live register-50 value.
`error_gain` duty cycle per (rad of error x kp). HL-2915 uses 0.05 and folds the rest
             into the fitted `error_gain_ratio`; HD-1910's 0.163 is already the
             effective figure, so its ratio stays 1.0.
`max_current` the register-44 goal-current cap. This is a *power budget* number as
             much as a physics one: 15 x 1.3 A is what the battery rail must survive.

Register before loading::

    import bam_actuators  # noqa: F401
"""

from __future__ import annotations

from bam.actuator import VoltageControlledActuator
from bam.actuators import actuators
from bam.parameter import Parameter
from bam.testbench import Pendulum

# HL-2915, from DuckBuddy's bench fit (Kp 16 held 0.1 N m at ~5 deg of error).
HL_ERROR_GAIN = 0.05
# The robot's register-44 cap (DuckBuddy robotd.toml writes 1300 mA at every startup).
HL_MAX_CURRENT = 1.3

# HD-1910, regressed over 36 unsaturated samples (duty = 5.2 * dq / kp, R^2 >= 0.94).
HD_ERROR_GAIN = 0.163
# Register 28 / what the servo actually clamps at.
HD_MAX_CURRENT = 3.25


class HL2915Actuator(VoltageControlledActuator):
  """Feetech HL-2915-C001: 9-14 V, 14.2 kg cm, coreless motor, 320:1 metal gear."""

  def __init__(self, testbench_class=Pendulum):
    super().__init__(
      testbench_class,
      vin=12.0,
      kp=16,
      error_gain=HL_ERROR_GAIN,
      max_pwm=1.0,
      max_current=HL_MAX_CURRENT,
    )

  def load_log(self, log: dict):
    super().load_log(log)
    if "current_limit_ma" in log:
      self.max_current = log["current_limit_ma"] / 1000.0

  def initialize(self):
    # Datasheet 1.39 N m stall / 1.5 A at 12 V; 0.91 N m/A measured on the robot.
    self.model.kt = Parameter(0.9, 0.3, 3.0)
    self.model.R = Parameter(8.0, 2.0, 20.0)
    self.model.armature = Parameter(0.005, 0.0001, 0.05)
    self.model.error_gain_ratio = Parameter(1.0, 0.1, 10.0)

  def get_extra_inertia(self) -> float:
    return self.model.armature.value

  def compute_control(self, q_target, q, dq, dt):
    duty = (q_target - q) * self.kp * self.error_gain * self.model.error_gain_ratio.value
    if self.max_current is not None:
      back_emf = self.model.kt.value * dq
      span = self.model.R.value * self.max_current / self.vin
      centre = back_emf / self.vin
      duty = self.backend.clamp(duty, centre - span, centre + span)
    duty = self.backend.clamp(duty, -self.max_pwm, self.max_pwm)
    return self.vin * duty


class HD1910Actuator(VoltageControlledActuator):
  """Feetech HD-1910-C001: 4-8.4 V, 12 kg cm at 6 V, the servo Feetech ships for the duck."""

  def __init__(self, testbench_class=Pendulum):
    super().__init__(
      testbench_class,
      vin=5.0,  # where the identification ran; kt/R are voltage-independent
      kp=32,
      error_gain=HD_ERROR_GAIN,
      max_pwm=1.0,
      max_current=HD_MAX_CURRENT,
    )

  def initialize(self):
    self.model.kt = Parameter(0.692, 0.3, 2.0)
    self.model.R = Parameter(3.75, 1.0, 15.0)
    self.model.armature = Parameter(0.00224, 0.0001, 0.05)

  def get_extra_inertia(self) -> float:
    return self.model.armature.value

  def compute_control(self, q_target, q, dq, dt):
    duty = (q_target - q) * self.kp * self.error_gain
    if self.max_current is not None:
      back_emf = self.model.kt.value * dq
      span = self.model.R.value * self.max_current / self.vin
      centre = back_emf / self.vin
      duty = self.backend.clamp(duty, centre - span, centre + span)
    duty = self.backend.clamp(duty, -self.max_pwm, self.max_pwm)
    return self.vin * duty


actuators["hl2915"] = lambda: HL2915Actuator(Pendulum)

# OpenMicroDuck bench class — used by tools/bam_params/hd1910/m5.json ("actuator":"hd1910").
actuators["hd1910"] = lambda: HD1910Actuator(Pendulum)

# ftservo-bam pit (方案阶段 B)：官方 actuators 表键是 "HD1910"，但官方 m6.json 写的是
# "actuator":"hd1910"。两边都要能 load。有官方类时：大写→官方控制律，小写仍给
# OpenMicroDuck m5；无官方包时两键都落到本文件的 HD1910Actuator。
try:
  from bam.feetech.actuator import HD1910Actuator as _OfficialHD1910  # type: ignore

  actuators["HD1910"] = lambda: _OfficialHD1910(Pendulum)
except Exception:
  actuators["HD1910"] = actuators["hd1910"]

# Cross-alias so either casing in a params JSON resolves.
actuators.setdefault("hd1910", actuators["HD1910"])
actuators.setdefault("HD1910", actuators["hd1910"])
