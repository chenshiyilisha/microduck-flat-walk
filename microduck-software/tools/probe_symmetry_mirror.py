"""Verify the bilateral mirror used by `tools/patch_joy_symmetry.py`.

Three independent checks, because the previous three rounds of this project
each died on a check that "looked reasonable" instead of one that could fail:

1. **Involution** -- mirroring twice must be the identity. Catches any
   permutation/sign table that is not a valid group action.
2. **Level consistency** -- the gait clock must move to p+pi (both entries
   negated). Asserted directly on the table, and separately that the
   permutation leaves the clock slots in place.
3. **Physics** -- the decisive one. Mirror the leg joint angles per the table
   and evaluate forward kinematics in MuJoCo: the two feet must *swap* their
   world positions (z_L' == z_R, x_L' == x_R, y_L' == -y_R). A sign error in
   any single joint shows up here as a mismatch of centimetres, not as a
   plausible-looking number.

The default pose is numerically antisymmetric for every leg joint
(hip_roll +-0.0873, hip_pitch -+0.4579, knee -+0.0049, ankle +-0.4530), which
is exactly why all leg joints are negated after the left<->right swap.

    .venv-mjlab/Scripts/python.exe tools/probe_symmetry_mirror.py
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
XML = ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/robot/microduck/robot_walk.xml"

# Actor obs layout measured from observation_manager (see patch docstring).
N_ACTOR = 63
G_JOINT_POS = slice(6, 20)
G_JOINT_VEL = slice(20, 34)
G_ACTIONS = slice(34, 48)
G_CLOCK = slice(61, 63)

HOME = {
    "left_hip_yaw": 0.0,
    "left_hip_roll": -0.0873,
    "left_hip_pitch": -0.4579,
    "left_knee": -0.0049,
    "left_ankle": 0.4530,
    "neck_pitch": 0.3491,
    "head_pitch": 0.3491,
    "head_yaw": 0.0,
    "head_roll": 0.0,
    "right_hip_yaw": 0.0,
    "right_hip_roll": 0.0873,
    "right_hip_pitch": 0.4579,
    "right_knee": 0.0049,
    "right_ankle": -0.4530,
}


def load_module():
    sys.path.insert(0, str(ROOT / ".venv-mjlab/Lib/site-packages"))
    from mjlab_microduck.tasks import symmetry

    return symmetry


def check_tables(sym) -> None:
    perm = torch.tensor(sym._OBS_PERM, dtype=torch.long)
    sign = torch.tensor(sym._OBS_SIGN, dtype=torch.float32)
    assert len(perm) == N_ACTOR == len(sign), (len(perm), len(sign))

    # 1. involution: perm twice = identity, sign twice = +1 everywhere
    perm2 = perm[perm]
    assert torch.equal(perm2, torch.arange(N_ACTOR)), "mirror is not an involution"
    assert torch.all(sign * sign == 1.0), "sign vector squared must be all ones"
    print(f"  [1] involution ok: perm(perm(x)) = x over {N_ACTOR} dims")

    # 2. gait clock: stays in place, both entries negated
    assert perm[G_CLOCK].tolist() == [61, 62], perm[G_CLOCK].tolist()
    assert sign[G_CLOCK].tolist() == [-1.0, -1.0], sign[G_CLOCK].tolist()
    print("  [2] gait clock ok: slots preserved, (sin, cos) -> (-sin, -cos) = p+pi")

    # The three 14-joint blocks must share one permutation/sign pattern.
    for blk in (G_JOINT_POS, G_JOINT_VEL, G_ACTIONS):
        p = (perm[blk] - blk.start).tolist()
        s = sign[blk].tolist()
        assert p == sym._JOINT_PERM, f"block at {blk} has a different permutation"
        assert s == sym._JOINT_SIGN, f"block at {blk} has a different sign vector"
    print("  [2b] joint_pos / joint_vel / actions share one L<->R pattern")


def check_physics(sym, trials: int = 200, seed: int = 0) -> None:
    import mujoco

    m = mujoco.MjModel.from_xml_path(str(XML))
    d = mujoco.MjData(m)

    order = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(m.njnt)]
    qadr = {n: m.jnt_qposadr[i] for i, n in enumerate(order) if n}
    # Find a free/base joint if present, keep the base fixed so the only thing
    # that can move the feet is the leg configuration.
    base_adr = None
    for i, n in enumerate(order):
        if m.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE:
            base_adr = m.jnt_qposadr[i]
    sid = {n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, n) for n in ("left_foot", "right_foot")}
    assert all(v >= 0 for v in sid.values()), sid

    rng = np.random.default_rng(seed)
    joints = [j for j in HOME]
    perm, sign = sym._JOINT_PERM, sym._JOINT_SIGN
    worst = 0.0
    for _ in range(trials):
        q = dict(HOME)
        for j in joints:
            if rng.random() < 0.7:  # perturb most joints, leave some at HOME
                q[j] += rng.normal(0.0, 0.25)

        def fk(qq):
            mujoco.mj_resetData(m, d)
            if base_adr is not None:
                d.qpos[base_adr : base_adr + 3] = (0.0, 0.0, 0.117)
                d.qpos[base_adr + 3 : base_adr + 7] = (1.0, 0.0, 0.0, 0.0)
            for j, v in qq.items():
                d.qpos[qadr[j]] = v
            mujoco.mj_forward(m, d)
            return d.site_xpos[sid["left_foot"]].copy(), d.site_xpos[sid["right_foot"]].copy()

        l0, r0 = fk(q)

        # Same expression the augmentation function uses: new[i] = sign[i] * old[perm[i]]
        base = np.array([q[j] for j in joints], dtype=np.float64)
        p = np.asarray(perm, dtype=np.int64)
        s = np.asarray(sign, dtype=np.float64)
        mirror = s * base[p]
        qm = dict(zip(joints, mirror.tolist()))
        l1, r1 = fk(qm)

        # Feet must swap: z and x swap, y flips sign.
        err = max(
            abs(l1[2] - r0[2]),
            abs(r1[2] - l0[2]),
            abs(l1[0] - r0[0]),
            abs(r1[0] - l0[0]),
            abs(l1[1] + r0[1]),
            abs(r1[1] + l0[1]),
        )
        worst = max(worst, err)

    print(f"  [3] physics ok: worst feet-swap error {worst * 1000:.4f} mm over {trials} poses")
    if worst > 1e-4:
        raise SystemExit(f"  ! mirror is not physically valid, err {worst * 1000:.2f} mm")


order_home = {j: j for j in HOME}


def check_shapes(sym) -> None:
    from tensordict import TensorDict

    b = 5
    obs = TensorDict(
        {"actor": torch.randn(b, N_ACTOR), "critic": torch.randn(b, 78)},
        batch_size=[b],
    )
    act = torch.randn(b, 14)
    aug_obs, aug_act = sym.microduck_vel_symmetry(env=None, obs=obs, actions=act)
    assert aug_obs["actor"].shape == (2 * b, N_ACTOR), aug_obs["actor"].shape
    assert aug_obs["critic"].shape == (2 * b, 78), aug_obs["critic"].shape
    assert aug_act.shape == (2 * b, 14), aug_act.shape
    assert torch.equal(aug_obs["actor"][:b], obs["actor"]), "first half must be untouched"
    assert torch.equal(aug_act[:b], act)
    aug2, _ = sym.microduck_vel_symmetry(env=None, obs=obs, actions=None)
    assert torch.equal(aug2["critic"], aug_obs["critic"])
    print(f"  [4] shapes ok: {b} -> {2 * b} rows, original half preserved bit-exact")


def main() -> int:
    sym = load_module()
    print("microduck mirror checks")
    check_tables(sym)
    check_shapes(sym)
    check_physics(sym)
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
