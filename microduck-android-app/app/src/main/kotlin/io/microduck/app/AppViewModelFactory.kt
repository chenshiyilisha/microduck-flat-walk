package io.microduck.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory

/**
 * ViewModel 工厂 —— 阶段 2 重构规划 §4「不引入 Hilt，ViewModel 用工厂手动构造」。
 *
 * ── 官方依据（developer.android.com/topic/libraries/architecture/viewmodel 一手核验）──
 * 官方明确「You should never manually create a ViewModel outside of a ViewModelProvider.Factory」：
 * 用 `viewModelFactory { initializer { … } }` + `APPLICATION_KEY` 从 [MicroDuckApp] 取
 * [io.microduck.app.core.RobotRepository] 单例注入，配 `by viewModels { Factory }` 委托。
 * **不**继承 AndroidViewModel（官方不推荐），[RobotRepository] 经 Application 单例注入。
 *
 * ── 为什么工厂放这里 ──
 * [MainViewModel] / [DriveViewModel] 都只依赖 [io.microduck.app.core.RobotRepository]，
 * 工厂逻辑相同，集中一处避免两处漂移。Activity 用 `by viewModels { AppViewModelFactory }` 即可。
 */
object AppViewModelFactory {

    /** [MainActivity] 用的 [MainViewModel] 工厂。 */
    val main = viewModelFactory {
        initializer {
            val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as MicroDuckApp
            MainViewModel(app.robotRepository)
        }
    }

    /** [DriveActivity] 用的 [DriveViewModel] 工厂。 */
    val drive = viewModelFactory {
        initializer {
            val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as MicroDuckApp
            DriveViewModel(app.robotRepository)
        }
    }
}
