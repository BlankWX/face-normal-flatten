# GitHub 发布准备

当前发布版本为 **1.1.0**，许可证为 **GPL-3.0-or-later**。

## 仓库内容

将 `dist/face_normal_flatten-1.1.0-source.zip` 解压后的顶层目录作为仓库目录。
其中已经包含 `.gitignore`、`.github/`、插件源码、文档和测试。

本地工作区的 `.local/` 保存开发资料，不属于公开仓库。浏览器手动上传时，使用干净源码包解压出的文件，不要拖入整个开发工作区。

## 发布前检查

```sh
python -m unittest discover -s tests -v
python tools/test_blender.py --blender blender
python tools/package_addon.py
```

检查 README 中的 Blender 兼容范围与版本号。插件作者署名为 **BlankWX**，已同步到插件信息和中英文 README。

## Release 附件

创建 `v1.1.0` 标签对应的 Release，说明可使用 [CHANGELOG](../CHANGELOG.md) 中的 1.1.0 条目。

- 安装包：`face_normal_flatten-1.1.0.zip`。
- 可选源码附件：`face_normal_flatten-1.1.0-source.zip`。
- 校验文件：`SHA256SUMS`。

`release-manifest.json` 记录公开文件及校验值，可同时附上。源码附件用于开发，插件附件用于 Blender 安装。

现有 CI 只测试和构建工作流附件，不会自动创建 GitHub Release。远程仓库、首次推送和正式发布由后续发布操作完成。
