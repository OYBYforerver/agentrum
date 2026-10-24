# Brand assets

Agentrum 的品牌标志为 **Asset Portal** 方案：图标由「拱门 + 门楣横杠」构成字母 **A**，右侧立柱构成 **I** —— 两个字母合起来就是 **AI**；拱门中的六边形核心（含 Sky 色印章点）代表被托管的资产本体，呼应 tag 不可变、可追溯的版本语义。

| 资产 | 用途 |
|---|---|
| `icon.svg`（512×512 圆角方块） | favicon、控制台侧边栏/登录页/项目落地页、文档站侧边栏 —— 一切小尺寸标识 |
| `logo-horizontal.svg`（640×160 字标横版） | README、官网导航、发布物封面 —— 一切门面横幅 |

## 使用规则

- 渐变底（Indigo `#4F46E5` → Cyan `#06B6D4`）+ 白色图形，深浅色背景通用；需要单色版（印刷/水印）时把渐变底换成 `#0F172A`，图形保持白色。
- 字标横版仅用于浅色背景；深色背景时主文字 `#0F172A` 改为 `#F8FAFC`，图标渐变底不变。
- 图标与字标必须成对使用，不得与其它风格混排。

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
