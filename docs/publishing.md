# GitHub 发布准备

待发布版本为 **1.2.0**，作者 **BlankWX**，许可证 **GPL-3.0-or-later**。目标为 `BlankWX/face-normal-flatten` 现有仓库的一次版本更新。

## 仓库内容

将 `dist/face_normal_flatten-1.2.0-source.zip` 解压后，使用顶层 `face-normal-flatten-1.2.0/` **内部的文件和目录**更新仓库根目录。保留现有仓库的 `.git` 与历史，不要把整个顶层目录作为子文件夹上传。

公开源码包含 `.github/`、插件源码、文档、测试及构建工具。文件管理器上传时确认 `.github/`、`.gitignore`、`.gitattributes` 和 `.editorconfig` 没有遗漏。

本地工作区的 `.local/` 保存开发资料，不属于公开仓库。使用干净源码包中的内容，不要上传整个开发工作区；安装包、校验文件和清单放入 Release 附件。

## 发布前检查

```sh
python -m unittest discover -s tests -v
python tools/test_blender.py --blender blender
python tools/package_addon.py
```

检查插件版本、README、发布说明和附件均对应 `1.2.0`。兼容性与已完成的测试范围见 [测试说明](testing.md)。本地代码未变、仅整理文档时，可核对代码校验值和已有 Blender 测试记录，并重新运行受影响的打包检查。

提交后检查 GitHub Actions 的 Python 测试与构建结果。CI 不运行 Blender 集成测试，不能替代本地 Blender 验证。

## Release 附件

在包含本次源码更新的提交上创建标签 **`v1.2.0`**，标题建议为 **Face Normal Flatten v1.2.0 · 动态法线过渡**。正文可直接使用 [v1.2.0 发布说明](releases/v1.2.0.md)。

附上同一次构建生成的四个文件：

- `face_normal_flatten-1.2.0.zip`：Blender 安装包。
- `face_normal_flatten-1.2.0-source.zip`：完整公开源码。
- `SHA256SUMS`：两个 ZIP 的 SHA-256 校验值。
- `release-manifest.json`：公开文件与校验值清单。

确认标签指向本次提交，再发布 Release。发布后下载两个 ZIP，对照 `SHA256SUMS` 核对，并确认安装包具有 `face_normal_flatten/__init__.py` 结构。

现有 CI 只测试并生成工作流附件，不会自动创建标签或 GitHub Release。本地整理完成不代表已经推送或发布。
