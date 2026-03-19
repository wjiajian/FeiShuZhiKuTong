# FeiShuZhiKuTong

连接飞书知识库，遍历空间文件树，识别与本地 NAS 的差异，并按目录结构下载/同步文件。

## 项目目标
本项目用于以下场景：
- 从飞书知识库递归获取文件结构。
- 对比本地 NAS 目录，找出新增或更新文件。
- 导出并下载飞书文档/表格到本地。
- 将下载结果同步到 NAS 目标目录。

核心流程：
`tenant_access_token -> space_list -> space_child_node -> export_tasks -> query_ticket -> download_file`

## 目录结构
```text
.
├─ feishu/
│  ├─ get_token.py         # 获取 tenant_access_token
│  ├─ get_kb_files.py      # 遍历知识空间并生成差异清单
│  └─ download_files.py    # 根据清单下载文件
├─ compare_move_file.py    # 将下载结果同步到 NAS（含保护机制）
├─ api_docs/               # 飞书 API 对照文档
└─ README.md
```

## 环境要求
- Python 3.7+
- 依赖：`requests`

安装依赖：
```bash
pip install requests
```

## 配置说明
### 1) `feishu/get_kb_files.py`
在文件顶部配置：
- `APP_ID` / `APP_SECRET`
- `SPACE_NAME`（目标知识空间名称）
- `NAS_ROOT_PATH`（用于对比的 NAS 根目录）

可选配置：
- `SYNC_FILTERS` + `USE_SYNC_FILTER`：白名单同步路径
- `BLACKLIST`：路径黑名单
- `FILE_EXTENSION_BLACKLIST`：扩展名黑名单

### 2) `feishu/download_files.py`
在文件顶部配置：
- `APP_ID` / `APP_SECRET`
- `FILES_TO_DOWNLOAD`（通常为 `files_to_download.json`）
- `SOURCE_DIR`（下载目标目录）

### 3) `compare_move_file.py`
- `PROTECTED_ITEMS`：保护路径（不会删除）
- 底部示例中的 `KB_TREE_JSON` / `SOURCE_DIR` / `DEST_DIR` 需按实际环境修改

## 推荐执行顺序
### 第一步：生成差异清单
```bash
python -m feishu.get_kb_files
```
产出：`space_list.json`、`kb_tree.json`、`files_to_download.json`

### 第二步：下载新增/更新文件
```bash
python -m feishu.download_files
```
结果：将文件写入 `SOURCE_DIR`，并尽量保持知识库目录结构。

### 第三步：同步到 NAS
```bash
python compare_move_file.py
```
建议先用演练模式（`dry_run=True`）核对操作，再执行正式同步。

## 输出文件说明
- `space_list.json`：可访问知识空间列表
- `kb_tree.json`：知识库完整文件树（含 token/type/修改时间）
- `files_to_download.json`：待下载文件列表

## 注意事项
- 请勿提交真实 `APP_ID`、`APP_SECRET`、token 到仓库。
- 飞书 `tenant_access_token` 有效期约 2 小时，下载脚本会尝试自动刷新。
- `slides`、`mindnote` 当前不支持导出，会被跳过。
- 执行 NAS 同步前，务必确认目标路径正确，并先演练。
- `compare_move_file.py` 的 `__main__` 是示例流程，生产环境建议按需修改后再运行。
