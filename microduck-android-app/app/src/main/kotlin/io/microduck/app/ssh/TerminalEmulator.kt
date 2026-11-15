package io.microduck.app.ssh

import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan

/**
 * 轻量网格终端模拟器：处理打印机字符 + 常见 ANSI/VT100 转义序列
 * （换行/回车/退格/TAB、CSI 光标移动/擦除、SGR 颜色），把远端字节流渲染成
 * 带颜色的文本。非完整 VT100（不实现 Alt 屏、换行模式等），但足够跑
 * `robotctl`/`systemctl`/`journalctl`/`ls`/`cat` 等命令行工具；全屏 TUI
 * （vim/htop）体验有限，属已知取舍。
 */
class TerminalEmulator(
    var cols: Int = 80,
    var rows: Int = 40,
    private val onUpdate: () -> Unit,
) {
    private class Cell(var ch: Char = ' ', var fg: Int = DEFAULT_FG)
    private val grid: MutableList<MutableList<Cell>> = ArrayList()
    private var cx = 0
    private var cy = 0
    private var curFg = DEFAULT_FG

    companion object {
        const val DEFAULT_FG = 0xFFE6EDF3.toInt() // 近白（匹配深色主题）
    }

    init { ensureRows() }

    private fun ensureRows() {
        while (grid.size < rows) grid.add(ArrayList<Cell>().also { row ->
            repeat(cols) { row.add(Cell()) }
        })
        // 列宽变化时不重建历史，仅保证当前行够宽
        for (row in grid) while (row.size < cols) row.add(Cell())
    }

    /** 喂入一段远端文本（可能含转义序列）。非线程安全，调用方应在 UI 线程。 */
    fun write(text: String) {
        var i = 0
        while (i < text.length) {
            val c = text[i]
            when {
                c == '\r' -> cx = 0
                c == '\n' -> { cx = 0; lineFeed() }
                c == '\b' -> if (cx > 0) cx--
                c == '\t' -> cx = ((cx / 8) + 1) * 8
                c == 0x1B.toChar() -> { // ESC
                    i = handleEscape(text, i)
                    continue
                }
                c.code < 0x20 -> { /* 其它控制字符忽略 */ }
                else -> {
                    if (cx >= cols) { cx = 0; lineFeed() }
                    if (cy >= grid.size) ensureRows()
                    grid[cy][cx].ch = c
                    grid[cy][cx].fg = curFg
                    cx++
                    if (cx >= cols) { cx = 0; lineFeed() }
                }
            }
            i++
        }
        onUpdate()
    }

    private fun lineFeed() {
        cy++
        if (cy >= rows) {
            grid.removeAt(0)
            grid.add(ArrayList<Cell>().also { row -> repeat(cols) { row.add(Cell()) } })
            cy = rows - 1
        }
    }

    /** 解析 ESC 序列。返回处理结束后应继续解析的索引（下一个字符位置）。 */
    private fun handleEscape(text: String, start: Int): Int {
        if (start + 1 >= text.length) return text.length
        return when (text[start + 1]) {
            '[' -> handleCsi(text, start + 2)
            ']' -> handleOsc(text, start + 2)   // 窗口标题等，直接跳过到 BEL/ST
            else -> start + 2 // 不认识的转义，跳过一个字符
        }
    }

    private fun handleOsc(text: String, start: Int): Int {
        var i = start
        while (i < text.length) {
            val c = text[i]
            if (c == 0x07.toChar() || (c == '\\' && i + 1 < text.length && text[i + 1] == '\\')) {
                return if (c == 0x07.toChar()) i + 1 else i + 2
            }
            i++
        }
        return text.length
    }

    /** 解析 CSI 序列：CSI Pn1;Pn2... <final byte> */
    private fun handleCsi(text: String, start: Int): Int {
        var i = start
        val params = StringBuilder()
        while (i < text.length) {
            val c = text[i]
            if (c in '0'..'9' || c == ';' || c == '?' || c == '!' || c == ' ' || c == '"') {
                params.append(c); i++
            } else {
                val finalByte = c
                applyCsi(params.toString(), finalByte)
                return i + 1
            }
        }
        return text.length
    }

    private fun applyCsi(params: String, finalByte: Char) {
        val nums = params.split(';').map { it.toIntOrNull() ?: 0 }
        val n = nums.firstOrNull() ?: 0
        when (finalByte) {
            'A' -> cy = (cy - (if (n == 0) 1 else n)).coerceAtLeast(0)       // 上
            'B' -> cy = (cy + (if (n == 0) 1 else n)).coerceAtMost(rows - 1)  // 下
            'C' -> cx = (cx + (if (n == 0) 1 else n)).coerceAtMost(cols - 1)  // 右
            'D' -> cx = (cx - (if (n == 0) 1 else n)).coerceAtLeast(0)        // 左
            'E' -> { cy = (cy + (if (n == 0) 1 else n)).coerceAtMost(rows - 1); cx = 0 } // 下一行开头
            'F' -> { cy = (cy - (if (n == 0) 1 else n)).coerceAtLeast(0); cx = 0 }       // 上一行开头
            'G' -> cx = (n - 1).coerceIn(0, cols - 1)                        // 绝对列
            'd' -> cy = (n - 1).coerceIn(0, rows - 1)                        // 绝对行
            'H', 'f' -> { // CUP：行;列
                val r = (nums.getOrNull(0) ?: 1) - 1
                val c = (nums.getOrNull(1) ?: 1) - 1
                cy = r.coerceIn(0, rows - 1); cx = c.coerceIn(0, cols - 1)
            }
            'J' -> eraseDisplay(n)   // 0 光标后 / 1 光标前 / 2 全屏
            'K' -> eraseLine(n)      // 0 行内光标后 / 1 行内光标前 / 2 整行
            'm' -> applySgr(nums)    // 颜色/属性
            else -> { /* 其它 CSI 忽略 */ }
        }
    }

    private fun eraseDisplay(mode: Int) {
        when (mode) {
            2 -> { for (row in grid) for (cell in row) { cell.ch = ' '; cell.fg = DEFAULT_FG } }
            0 -> { for (x in cx until cols) grid[cy][x].ch = ' '
                    for (y in cy + 1 until rows) for (x in 0 until cols) grid[y][x].ch = ' ' }
            1 -> { for (x in 0..cx) grid[cy][x].ch = ' '
                    for (y in 0 until cy) for (x in 0 until cols) grid[y][x].ch = ' ' }
        }
    }

    private fun eraseLine(mode: Int) {
        when (mode) {
            2 -> for (x in 0 until cols) grid[cy][x].ch = ' '
            0 -> for (x in cx until cols) grid[cy][x].ch = ' '
            1 -> for (x in 0..cx) grid[cy][x].ch = ' '
        }
    }

    /** SGR：仅处理 16/256 色前景（30-37/90-97/38;5;n），背景与属性忽略。 */
    private fun applySgr(nums: List<Int>) {
        if (nums.isEmpty()) { curFg = DEFAULT_FG; return }
        var i = 0
        while (i < nums.size) {
            val code = nums[i]
            when {
                code == 0 -> curFg = DEFAULT_FG
                code in 30..37 -> curFg = ansi256(code - 30)
                code in 90..97 -> curFg = ansi256(code - 90 + 8)
                code == 39 -> curFg = DEFAULT_FG
                code == 38 && i + 2 < nums.size && nums[i + 1] == 5 -> {
                    curFg = ansi256(nums[i + 2]); i += 2
                }
                else -> { /* 背景/加粗等忽略 */ }
            }
            i++
        }
    }

    private val palette = intArrayOf(
        0xFF4E4E4E.toInt(), 0xFFCC4040.toInt(), 0xFF4E9A06.toInt(), 0xFFC4A000.toInt(),
        0xFF3465A4.toInt(), 0xFF75507B.toInt(), 0xFF06989A.toInt(), 0xFFD3D7CF.toInt(),
        0xFF555753.toInt(), 0xFFEF5350.toInt(), 0xFF8AE234.toInt(), 0xFFFCE94F.toInt(),
        0xFF729FCF.toInt(), 0xFFAD7FA8.toInt(), 0xFF34E2E2.toInt(), 0xFFEEEEEC.toInt(),
    )

    private fun ansi256(idx: Int): Int = if (idx in palette.indices) palette[idx] else DEFAULT_FG

    /** 把当前网格渲染成带前景色的 SpannableString。 */
    fun render(): CharSequence {
        val sb = SpannableStringBuilder()
        for (y in 0 until rows) {
            val row = grid[y]
            var x = 0
            while (x < cols) {
                if (row[x].ch != ' ') break
                x++
            }
            if (x == cols) continue // 整行空，跳过
            val line = StringBuilder()
            for (x in 0 until cols) line.append(row[x].ch)
            val lineStr = line.toString().trimEnd()
            val lineStart = sb.length
            sb.append(lineStr).append('\n')
            // 颜色：按单元格分色太碎，简化为「整行取首非空单元格的前景色」。
            var fx = 0
            while (fx < cols && row[fx].ch == ' ') fx++
            if (fx < cols && row[fx].fg != DEFAULT_FG) {
                sb.setSpan(
                    ForegroundColorSpan(row[fx].fg), lineStart, lineStart + lineStr.length,
                    SpannableStringBuilder.SPAN_EXCLUSIVE_EXCLUSIVE,
                )
            }
        }
        return sb
    }
}
