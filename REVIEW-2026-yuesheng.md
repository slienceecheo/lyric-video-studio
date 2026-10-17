# lyric-video-studio 技能复盘（来自《月声尽，心灯明》项目）

本轮实际做过的事：一首 4:15 的歌，47 页横屏整曲 + 9 页竖屏高潮短片，前后 5 次交付（首版 → 显示行上下颠倒修复 → 呼吸抖动修复 → 换 LRC 重排时间轴 → 加中秋/元宵氛围层 → 去掉音源/BV 行）。
下面每一条都写清「技能里原本怎么写的 / 这次实测是什么 / 改成了什么」。
共 12 处改动：**3 处纠正技能自己的错误建议**、4 处新增缺陷类、5 处新增工具、其余是环境与流程。

---

## 一、技能原来写错的三处（这三处直接造成了本次最贵的排查）

### 1. 「显示行位置呼吸」——技能在推荐那个 bug
- 原来（`references/renderer.md` §9 第 2 条）：`the display block moves by -BR_DEPTH*size*breath(t)`（150px 字 ±1.5px），`pitfalls.md` 的整数像素条目还教「把 jump 当成量化，不要当成 flicker」。
- 实测：PIL 按整数 y 光栅化，±1.5px 的正弦让整行字**每 1.45s 跳两整像素**，相邻帧 mean|dL| = **0.36**，比一次换页还大。后果是 `verify_assembly.py` 的 D 段在 **两个不是页切点的帧**上报 `*** DISCONTINUITY ***`（seam/floor 比 54.25 和 25.74），我顺着去查编码器、concat 列表、chunk 完整性——全是好的。这条 bug 穿过 3 次交付没被发现，因为 `motion_probe.py` 早就报过 jump，而技能教我把 jump 读成量化。
- 改成：位置只留给入场（进度驱动、会结束），呼吸走**墨色密度** `fill = mix(fill, bg, max(0, amp))`（8 bit 填充级别 = 很多个看不见的台阶）。并把实测代价写进 SKILL.md 非协商条款 10 和 pitfalls。
- 验证（技能新工具 `diff_cell.py` 在同一帧对）：修复前 0.359 → 修复后 **0.006**。

### 2. 得意黑字宽
- 原来：0.40 em/字（文档与旧 handoff 都是这个数）。
- 实测：**0.435–0.445 em**。后果是「行数最少优先」的 fit 策略把 7 字行压到 98px（可读性崩），而两行能给到 143–176px。
- 改成：`fit_display` 策略 + 实测字宽写进 SKILL.md 环境段与 `renderer.md` §8 第 6 条；同时加入「显示块要用自身墨迹 bbox 上抬，因为中文逗号/、会探到基线以下撞上字幕」。

### 3. 清空 `out/` 的建议没有区分「输入」和「产物」
- 原来（`assembly.md` §3）：`Clear out/ whenever the cut table ... changes`。
- 实测：`pages.json`（页表）和 `lrc_lines.json` 当初被写进了 `out/`，一次 `Remove-Item -Recurse` 把它们删了，8 个 worker **0.4 秒内全部 rc=1**，`FileNotFoundError: ...\out\pages.json`。
- 改成：新增 SKILL.md 非协商条款 12「**输入不是产物**」——页表/LRC/包络/官方 LRC 落在项目根，`out/` 只放可重生产物；清空必须按名字正则限制，并给出可直接粘贴的 PowerShell 命令。

---

## 二、新增的缺陷类（技能里原来完全没有）

### 4. 歌词读反了：draw order ≠ reading order
- 现象：`layout_audit` 0/0、`lrc_check` `mismatches: 0`、显示块 box 与 plan 完全一致——但 28 个两行页全部把第 2 行画在上面，**歌词倒着读**。原因是 SEG 的 `big` 按阅读顺序编写（第 0 行在最上），draw loop 却用 `yb = yb0 - j*lh` 让第 0 行落在最下。所有「比字符串」的检查都在比 plan，plan 是对的。
- 修法：`yb = yb0 - (nl-1-j)*lh`；box 并集不变，所以不用重排。
- 检查：`lrc_check.py` 新增第五条 **ORDER**——渲染稳态一帧，按正确 draw loop 的公式切每条阅读行应占的带，单独排每一个候选行，比较 z 归一化的**逐列墨量**，本行必须赢自己的带（两条候选行相关 >0.995 视为不可判）。结果 56 带全部通过。
- **负控制**：复制模块 → 在副本里把规则改回 `- j*lh` → 要求检查器 56 带全部失败并打印 `-- the display is drawn upside down` → 删副本。一个从没失败过的检查不算证据，这条写进了 `lyrics-and-cards.md` §2。

### 5. 组装 seam 报点如果不是页切点 → 是渲染器在跳
- 现象：A 段完美（40 段连续、帧数吻合、sum==NFR），D 段却报 `DISCONTINUITY`。
- 判别法（两个新工具，一分钟出结论）：`seam_probe.py` 按**帧号**解码交付文件（`select` 滤镜，绝不用 `-ss`，避免「seek 背锅」），把 mp4 逐帧差和模块逐帧差并排打印：`film dL` 尖而 `|mp4-film|` 平 = 渲染器；只有 mp4 尖 = 编码/拼接；`|mp4-film|` 单帧尖 = 丢帧。`diff_cell.py` 给逐格 mean|dL| 图 + 变化像素 bbox + 对比拉伸 PNG，bbox 直接说出「哪个元素动了」。
- 标定值（写进技能）：页内 0.005–0.032/帧，换页 0.35+，量化位置呼吸 0.36。

### 6. B 段像素偏移的噪声 argmin
- 现象：`--points` 取到静态页时 B 报 `SHIFT -10 / +30`，而 C 段同一帧说 `weak (the picture barely moves here)`；重渲一次数字就变。
- 改成：`--points` 必须机械生成（页表 `f0 + 10`，`n >= 40` 的页），且「B 报偏移而 C 说 weak ⇒ 噪声 argmin」写进 `assembly.md` §6；真偏移的特征是同一 chunk 内所有点都重复。

### 7. 氛围层读成别的东西（`背景很单调` 那一轮）
五种实测读错的方式 + 8 条契约，进 `renderer.md` 新 §4b 和 pitfalls：
- 粒子「出生/死亡」做成事件 → 全部 wrap，y = (相位 + t*速度) mod 1；
- 同心 AA 椭圆叠 alpha 出**方格纸条纹** → 内部用 numpy 径向渐变 `(clip(1-d)**1.7)*(0.16+0.62*flux)`，AA 只画轮廓；
- 圆角矩形「灯笼」读成灰色 UI 卡片 → 椭圆纸身 + 解析裁剪的肋骨 + 提梁 + 流苏；
- 每帧构造半径千级 AA 椭圆画光晕 → 一次缓存 256×256 `glow_sprite()` + `putalpha(point(...))`；
- 月牙用「背景色圆盘横移」当相位线 → 越界被**方切成矩形**，在歌词后面印出一块灰 → 两张 L mask 求交（`ImageChops.multiply`）。
- 契约：背景层画在文字之前；穿过文字列时按面积压 alpha（~0.38）；密度由 `progress(t)` 而非节拍驱动；alpha 分 ~16 档按 (polarity, bucket) 缓存；`diff_cell` 连续帧必须留在 HUD 量级（~0.02）。

### 8. Windows 三坑
- **默认文件编码是 GBK**：`open(path)` 读官方 LRC → `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`。已写入：所有读写显式 `encoding="utf-8"`（BOM 用 `utf-8-sig`），脚本头 `sys.stdout.reconfigure(encoding="utf-8")`。
- **`[` `]` 被当通配符**：源文件名 `...［BV1xxxxxxxxxx］.m4a`，`Copy-Item` **静默复制 0 字节且报成功** → 一切含方括号的路径用 `-LiteralPath`，并回读字节数确认。
- PowerShell 无 heredoc / 引号嵌套会烂 → 写成 `.py` 再跑（原有条目保留）。

---

## 三、沉淀进 `scripts/` 的新工具（全部 py_compile + 在本项目 film.py 上冒烟通过）

| 工具 | 作用 |
|---|---|
| `verify_short.py` | 竖版交付物 8 段验证：流参数 / 时长与解码帧数 / moov 顺序 / 厂商标签与标题 / **音轨与源 8 kHz 解码互相关（±1 帧）+ 起点非静音** / LRC 起点 / 逐帧像素抽查 / **每个 chunk 接缝前后各 1 帧共 3 帧逐帧比对**（陈旧 chunk 能骗过抽查，骗不过接缝）/ 抽帧供肉眼复核 |
| `delivery_manifest.py` | 交付清单生成器：帧号↔歌曲时间、容器偏移、两份交付物的分区与逐页表（带官方 LRC 戳）、短片首句对位。技能一直要求「ship a manifest」但没有生成器 |
| `seam_probe.py` | 判定 seam 是渲染器还是编码：按帧号解码并排比 |
| `diff_cell.py` | 两帧差在哪：逐格图 + bbox + PNG |
| `page_sheet.py` | 直接从模块出整片接触表（兼容 `frame(k)` 与 `frame_t(t,k)` 两种形态），是「先看再看」的廉价视觉回路 |

另：`assets/lrc_check_example.py` 增补可选 **ORDER** 检查（模块暴露 `layout/display/frame/bg_col/fg_col/XR` 时自动启用，否则打印 skipped），并在 docstring 里写清为什么 plan 级检查看不见它。

---

## 四、我没有改动、但需要你决定的两件事

1. **同一文本 + 统一偏移的两个 LRC 无法用音频判别。** 这次两个文件 40 行文本完全相同、每个戳差 **恰好 -2.175 s**；我做了四项取证（±3s 内最强起振、对数谱图叠加、乐句间隙检测、戳前后呼吸统计）**全部无判别力**（密集编曲每秒约 4 个起振，人声频段被伴奏填满）。技能里我只写了处理流程（陈述证据 → 问用户 → 备份 `_lvstmp/tl_<name>/` 使回滚=复制+重渲 → 报告「单向 refit」这条早期网格的旁证），**没有**去改 `assets/timeline_gen.py` 的 `score`，因为再多探测也没有判别力，加了会给出虚假信心。如果你希望技能里放一个「统一偏移候选打分表」的示例输出格式，我可以补。
2. **`timeline_gen.py` 的索引硬化值得吸收。** 这次 `Env.i_at(t)` 用名义 hop（`t/0.005`）而不是真实时间数组（真实 hop 4.9887 ms），1.0023 倍的比例把搜索窗口逐渐推后（t=235s 时晚了 0.53s），**伪造出一条单调漂移**，差点让我重写整张时间表。修法是 `np.searchsorted(self.t, t)`，并且包络帧要用**后沿** `(k+w)/RATE` 标注才会让 flux 峰落在起振上。这两点目前只在 `pitfalls.md`，没有进 `timeline_gen.py`。要不要我顺手硬化？

---

## 五、验证记录

- `python -m py_compile` 对 5 个新脚本 + `lrc_check_example.py` 全部通过。
- `diff_cell.py 223 224 --mod film.py` → `mean|dL| 0.006`（修复前同一帧对是 0.359），说明工具可用且「位置呼吸」结论仍然成立。
- `page_sheet.py --spec 0,10,38,46` → 4 页一张图，`frame(k)` 形态正确。
- `seam_probe.py <交付 mp4> 223 225 --mod film.py` → `film dL 0.006 / 0.005`，`|mp4-film|` 平在 1.38（编码往返误差），即该段无跳变、交付忠实的正确读法。
- 文档结构：`renderer.md` 标题编号 1–9 + 4b 完整；SKILL.md 22.4KB、pitfalls 32.2KB、assembly 12.6KB、renderer 19.6KB、lyrics-and-cards 11.2KB、pipeline 16.4KB。
