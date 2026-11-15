package io.microduck.app.core

import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/**
 * 缓慢旋转的鸭子仿真模型 —— **纯 JVM 几何层**（零 Android 依赖，可被 core 自检真跑）。
 *
 * ── 为什么 3D 数学要放在 core，而不是塞进 View ──
 * 项目铁律：坐标系/轴/单位的量必须用**两条独立算法**互算，且「只测内部函数不测 CLI」
 * 是假绿。`app/` 的自定义 View 在 JVM 自检里跑不起来（android.graphics.Canvas 是 stub），
 * 所以旋转/投影/深度排序全部下沉到这里；View 只负责把算好的屏幕坐标画到 Canvas。
 *
 * ── 平台依据 ──
 * Google Android 平台文档 `android.graphics.Camera`（API 1）：
 *   "A camera instance can be used to compute 3D transformations and generate a matrix
 *    that can be applied, for instance, on a Canvas." —— 即 3D 变换 + 2D Canvas 绘制
 * 是平台既有的标准路径，无需 OpenGL ES / Sceneform / 第三方 3D 引擎，
 * 也无需新增 Gradle 依赖（本项目离线构建，Google 域名不通）。
 * 官方文档另注「真正的 3D 图形应扩展 SurfaceView」；本模型是**软件透视投影的线框/标记**，
 * 本质是 2D Canvas 绘制，正落在 Camera/Matrix 的适用范围内。
 *
 * ── 坐标约定（写死，禁止隐式漂移）──
 * y 向上，+z 朝向观察者（喙的方向），x 向右。绕 Y 轴旋转：`+x` 转向 `-z`。
 * 透视：`scale = D / (D - z')`，D=CAMERA_DISTANCE；z' 越大（越近）scale 越大。
 * 深度 `depth = z'`，绘制时升序（远的先画，painter's algorithm）。
 */
data class Vec3(val x: Float, val y: Float, val z: Float)

data class ProjectedPoint(val x: Float, val y: Float, val depth: Float)

data class ProjectedLine(val a: ProjectedPoint, val b: ProjectedPoint, val avgDepth: Float)

data class ModelNode(val part: RobotPart, val p: Vec3, val label: String = part.label)

data class ModelFrame(
    val nodes: List<Pair<ModelNode, ProjectedPoint>>,
    val hull: List<ProjectedLine>,
    val bones: List<ProjectedLine>,
) {
    /** 异常部位（WARN/CRITICAL）在屏幕上的位置，供 View 画光晕与标签。 */
    fun flagged(severityOf: (RobotPart) -> Severity): List<Pair<ModelNode, ProjectedPoint>> =
        nodes.filter { (n, _) -> severityOf(n.part).let { it == Severity.WARN || it == Severity.CRITICAL } }
}

object DuckModelGeometry {

    const val CAMERA_DISTANCE: Float = 4.0f
    private const val FOCAL_RATIO: Float = 0.26f

    /**
     * 部位锚点：15 关节按 `RobotParts.JOINT_NAMES` 顺序，坐标取自简化站姿骨架
     * （`duck-control/src/model.rs:DEFAULT_POSITION` 是站姿、HOME 非零位；
     * 这里只做**示意几何**，不是运动学解算，绝不冒充真实关节位姿）。
     */
    val NODES: List<ModelNode> = listOf(
        ModelNode(RobotPart.LEFT_HIP_YAW, Vec3(-0.34f, -0.30f, 0.00f)),
        ModelNode(RobotPart.LEFT_HIP_ROLL, Vec3(-0.38f, -0.48f, 0.00f)),
        ModelNode(RobotPart.LEFT_HIP_PITCH, Vec3(-0.38f, -0.66f, 0.00f)),
        ModelNode(RobotPart.LEFT_KNEE, Vec3(-0.38f, -1.02f, 0.06f)),
        ModelNode(RobotPart.LEFT_ANKLE, Vec3(-0.38f, -1.40f, 0.00f)),
        ModelNode(RobotPart.NECK_PITCH, Vec3(0.00f, 0.52f, 0.00f)),
        ModelNode(RobotPart.HEAD_PITCH, Vec3(0.00f, 0.90f, 0.02f)),
        ModelNode(RobotPart.HEAD_YAW, Vec3(0.00f, 1.12f, 0.02f)),
        ModelNode(RobotPart.HEAD_ROLL, Vec3(0.00f, 1.32f, 0.02f)),
        ModelNode(RobotPart.MOUTH, Vec3(0.00f, 1.00f, 0.44f)),
        ModelNode(RobotPart.RIGHT_HIP_YAW, Vec3(0.34f, -0.30f, 0.00f)),
        ModelNode(RobotPart.RIGHT_HIP_ROLL, Vec3(0.38f, -0.48f, 0.00f)),
        ModelNode(RobotPart.RIGHT_HIP_PITCH, Vec3(0.38f, -0.66f, 0.00f)),
        ModelNode(RobotPart.RIGHT_KNEE, Vec3(0.38f, -1.02f, 0.06f)),
        ModelNode(RobotPart.RIGHT_ANKLE, Vec3(0.38f, -1.40f, 0.00f)),
        ModelNode(RobotPart.TORSO, Vec3(0.00f, 0.00f, 0.00f)),
        ModelNode(RobotPart.BATTERY, Vec3(0.00f, -0.18f, -0.24f)),
        ModelNode(RobotPart.CPU, Vec3(0.00f, 0.20f, -0.20f)),
        ModelNode(RobotPart.IMU, Vec3(0.00f, 1.20f, 0.16f)),
        ModelNode(RobotPart.BUS, Vec3(0.00f, -0.12f, 0.20f)),
        ModelNode(RobotPart.LINK, Vec3(0.00f, 0.34f, -0.34f)),
    )

    /** 骨架：躯干→颈→头、躯干→左右腿、脚板。 */
    val BONES: List<Pair<RobotPart, RobotPart>> = listOf(
        RobotPart.TORSO to RobotPart.NECK_PITCH,
        RobotPart.NECK_PITCH to RobotPart.HEAD_PITCH,
        RobotPart.HEAD_PITCH to RobotPart.HEAD_YAW,
        RobotPart.HEAD_YAW to RobotPart.HEAD_ROLL,
        RobotPart.HEAD_PITCH to RobotPart.MOUTH,
        RobotPart.TORSO to RobotPart.LEFT_HIP_YAW,
        RobotPart.LEFT_HIP_YAW to RobotPart.LEFT_HIP_ROLL,
        RobotPart.LEFT_HIP_ROLL to RobotPart.LEFT_HIP_PITCH,
        RobotPart.LEFT_HIP_PITCH to RobotPart.LEFT_KNEE,
        RobotPart.LEFT_KNEE to RobotPart.LEFT_ANKLE,
        RobotPart.TORSO to RobotPart.RIGHT_HIP_YAW,
        RobotPart.RIGHT_HIP_YAW to RobotPart.RIGHT_HIP_ROLL,
        RobotPart.RIGHT_HIP_ROLL to RobotPart.RIGHT_HIP_PITCH,
        RobotPart.RIGHT_HIP_PITCH to RobotPart.RIGHT_KNEE,
        RobotPart.RIGHT_KNEE to RobotPart.RIGHT_ANKLE,
        RobotPart.TORSO to RobotPart.BATTERY,
        RobotPart.TORSO to RobotPart.CPU,
        RobotPart.TORSO to RobotPart.BUS,
    )

    /** 躯干/头部椭球线框：让模型是「旋转的实体鸭子」而不是火柴人。 */
    val HULL: List<Pair<Vec3, Vec3>> = buildList {
        addAll(ellipsoid(Vec3(0f, -0.05f, 0f), 0.56f, 0.60f, 0.42f, meridians = 8, parallels = 3))
        addAll(ellipsoid(Vec3(0f, 1.10f, 0.02f), 0.42f, 0.38f, 0.40f, meridians = 8, parallels = 3))
        // 喙：从头部前缘伸出的锥体（4 条棱 + 底部环）
        val tip = Vec3(0f, 1.00f, 0.72f)
        for (i in 0 until 6) {
            val a = i * Math.PI.toFloat() / 3f
            val base = Vec3(0.16f * cos(a), 1.00f + 0.10f * sin(a), 0.38f)
            add(base to tip)
            val b = (i + 1) * Math.PI.toFloat() / 3f
            add(base to Vec3(0.16f * cos(b), 1.00f + 0.10f * sin(b), 0.38f))
        }
        // 两只脚板
        for (sx in listOf(-0.38f, 0.38f)) {
            add(Vec3(sx - 0.16f, -1.48f, 0.06f) to Vec3(sx + 0.16f, -1.48f, 0.06f))
            add(Vec3(sx - 0.16f, -1.48f, 0.30f) to Vec3(sx + 0.16f, -1.48f, 0.30f))
            add(Vec3(sx - 0.16f, -1.48f, 0.06f) to Vec3(sx - 0.16f, -1.48f, 0.30f))
            add(Vec3(sx + 0.16f, -1.48f, 0.06f) to Vec3(sx + 0.16f, -1.48f, 0.30f))
            add(Vec3(sx, -1.40f, 0f) to Vec3(sx, -1.48f, 0.18f))
        }
    }

    private fun ellipsoid(
        c: Vec3, rx: Float, ry: Float, rz: Float, meridians: Int, parallels: Int,
    ): List<Pair<Vec3, Vec3>> {
        val out = mutableListOf<Pair<Vec3, Vec3>>()
        fun at(u: Float, v: Float) = Vec3(
            c.x + rx * cos(u) * cos(v),
            c.y + ry * sin(v),
            c.z + rz * sin(u) * cos(v),
        )
        for (i in 0 until meridians) {
            val u0 = 2f * Math.PI.toFloat() * i / meridians
            val u1 = 2f * Math.PI.toFloat() * (i + 1) / meridians
            for (j in -parallels..parallels) {
                val v0 = (Math.PI.toFloat() / 2f) * j / (parallels + 1)
                val v1 = (Math.PI.toFloat() / 2f) * (j + 1) / (parallels + 1)
                if (j < parallels) out.add(at(u0, v0) to at(u0, v1))
                out.add(at(u0, v0) to at(u1, v0))
            }
        }
        return out
    }

    /** 绕 Y 轴旋转（主算法）。+x 转向 -z。 */
    fun rotateY(p: Vec3, degrees: Double): Vec3 {
        val a = Math.toRadians(degrees)
        val c = cos(a).toFloat()
        val s = sin(a).toFloat()
        return Vec3(p.x * c + p.z * s, p.y, -p.x * s + p.z * c)
    }

    /**
     * 绕 Y 轴旋转（**第二条独立路径**：复合两次半角）。
     * 自检用它和 [rotateY] 互算同一角度 —— 项目铁律「坐标/轴/单位必须两条独立算法互算」。
     * 这不是同一个公式抄两遍：它走的是旋转群复合律 R(a)=R(a/2)·R(a/2)。
     */
    fun rotateYTwice(p: Vec3, degrees: Double): Vec3 = rotateY(rotateY(p, degrees / 2.0), degrees / 2.0)

    /** 透视投影；画布尺寸用像素，返回屏幕坐标 + 深度。 */
    fun project(p: Vec3, width: Float, height: Float): ProjectedPoint {
        val focal = min(width, height) * FOCAL_RATIO
        val denom = (CAMERA_DISTANCE - p.z).coerceAtLeast(0.1f)
        val scale = CAMERA_DISTANCE / denom
        return ProjectedPoint(
            x = width / 2f + p.x * focal * scale,
            y = height / 2f - p.y * focal * scale,
            depth = p.z,
        )
    }

    /** 生成一帧：所有锚点、壳体线、骨架都已旋转+投影，并按深度排序（远→近）。 */
    fun frame(angleDegrees: Double, width: Float, height: Float): ModelFrame {
        val byPart = NODES.associateBy { it.part }
        val nodes = NODES.map { n -> n to project(rotateY(n.p, angleDegrees), width, height) }
            .sortedBy { it.second.depth }
        val hull = HULL.map { (a, b) ->
            val pa = project(rotateY(a, angleDegrees), width, height)
            val pb = project(rotateY(b, angleDegrees), width, height)
            ProjectedLine(pa, pb, (pa.depth + pb.depth) / 2f)
        }.sortedBy { it.avgDepth }
        val bones = BONES.mapNotNull { (a, b) ->
            val na = byPart[a] ?: return@mapNotNull null
            val nb = byPart[b] ?: return@mapNotNull null
            val pa = project(rotateY(na.p, angleDegrees), width, height)
            val pb = project(rotateY(nb.p, angleDegrees), width, height)
            ProjectedLine(pa, pb, (pa.depth + pb.depth) / 2f)
        }.sortedBy { it.avgDepth }
        return ModelFrame(nodes, hull, bones)
    }

    /** 自检用：两个 Vec3 是否在容差内相等。 */
    fun near(a: Vec3, b: Vec3, eps: Float = 1e-4f): Boolean =
        abs(a.x - b.x) <= eps && abs(a.y - b.y) <= eps && abs(a.z - b.z) <= eps
}
