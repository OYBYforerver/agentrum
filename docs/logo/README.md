# Brand assets

Agentrum 的品牌标志采用 **Asset Portal（资产门户）** 方案（提案文件见本目录 `concepts/`，含三方案对比预览 `concepts/preview.html`；Nexus、Orbit 两个未采用方向一并归档备查）：

| 资产 | 用途 |
|---|---|
| `icon.svg`（512×512 圆角方块，拱门 + 六边形核心） | favicon、控制台侧边栏/登录页/项目落地页、文档站侧边栏 —— 一切小尺寸标识 |
| `logo-horizontal.svg`（640×160 字标横版） | README、官网导航、发布物封面 —— 一切门面横幅 |

## 设计语义与使用规则

- **拱门** = 注册中心的入口：项目从这里发布资产，其他项目从这里订阅。
- **门中悬浮的六边形核心** = 被托管的资产本体，中心亮点像一枚「印章」，呼应 tag 不可变、可追溯的版本语义。
- 渐变底（Indigo `#4F46E5` → Cyan `#06B6D4`）+ 白色图形，深浅色背景通用；需要单色版（印刷/水印）时把渐变底换成 `#0F172A`，图形保持白色。
- 字标横版仅用于浅色背景；深色背景时主文字 `#0F172A` 改为 `#F8FAFC`，图标渐变底不变。
- 图标与字标必须成对使用、保持同一方案，不得与其他方案混排。

## 色板

| 角色 | 色值 |
|---|---|
| 主色 Indigo 600 | `#4F46E5` |
| 渐变终点 Cyan 500 | `#06B6D4` |
| 点缀 Sky 500 | `#0EA5E9` |
| 文字 Slate 900 | `#0F172A` |
| 次要文字 Slate 500 | `#64748B` |
| 浅背景 Slate 50 | `#F8FAFC` |

## 接线位置

- README / README.en：`docs/logo/logo-horizontal.svg`
- 控制台：`ui/public/icon.svg`（favicon + 登录页 + 侧边栏 + 项目落地页）
- 文档站：`docs/site/assets/icon.svg`（mkdocs-material `theme.logo` / `theme.favicon`）
