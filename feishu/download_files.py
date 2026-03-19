# -*- coding: utf-8 -*-

"""
本程序用于从飞书知识库下载文件到本地源文件夹。

工作流程:
1. 读取 files_to_download.json（由 feishu_get_kb_files.py 生成）。
2. 获取飞书 tenant_access_token。
3. 根据文件类型选择下载方式：
   - 云文档（docx/doc/sheet/bitable）：创建导出任务 → 轮询状态 → 下载导出文件
   - 普通文件（file）：直接通过 Drive API 下载
4. 将文件保存到 SOURCE_DIR，保持知识库的目录结构。

注意事项:
- 导出的文件有 10 分钟有效期，程序会在导出完成后立即下载。
- 支持断点续传：已下载的文件会自动跳过。
- token 过期（2小时）时会自动刷新。

使用前请确保:
- 已安装 requests 库: `pip install requests`
- 已运行 feishu_get_kb_files.py 生成 files_to_download.json
"""

import os
import json
import time
import requests
from typing import Optional

from feishu.get_token import get_feishu_tenant_access_token

# ============================================================
# 基础配置
# ============================================================
APP_ID = ""  # 飞书应用 App ID
APP_SECRET = ""  # 飞书应用 App Secret
FILES_TO_DOWNLOAD = "files_to_download.json"  # 需要下载的文件列表（来自 feishu_get_kb_files.py）
SOURCE_DIR = ""  # 下载目标目录（即 compare_move_file.py 的 source_folder）
# ============================================================

# ============================================================
# 下载控制参数
# ============================================================
POLL_INTERVAL_SECONDS = 3    # 导出任务轮询间隔（秒）
POLL_MAX_ATTEMPTS = 20       # 最大轮询次数（20 × 3s = 60s）
REQUEST_INTERVAL_SECONDS = 0.7  # API调用间隔，避免触发速率限制（100次/分钟）
# ============================================================

# 飞书 obj_type 到导出格式的映射（与 feishu_get_kb_files.py 保持一致）
OBJ_TYPE_EXPORT_MAP = {
    "docx": (".docx", "docx"),
    "doc": (".docx", "docx"),
    "sheet": (".xlsx", "xlsx"),
    "bitable": (".xlsx", "xlsx"),
}


def get_auth_header(token: str) -> dict:
    """返回飞书API认证请求头。"""
    return {"Authorization": f"Bearer {token}"}


def create_export_task(obj_token: str, obj_type: str, token: str) -> Optional[str]:
    """
    创建飞书文档导出任务。

    Args:
        obj_token: 文档的 obj_token。
        obj_type: 文档类型（docx/doc/sheet/bitable）。
        token: tenant_access_token。

    Returns:
        成功返回 ticket（任务ID），失败返回 None。
    """
    url = "https://open.feishu.cn/open-apis/drive/v1/export_tasks"
    headers = get_auth_header(token)
    headers["Content-Type"] = "application/json; charset=utf-8"

    mapping = OBJ_TYPE_EXPORT_MAP.get(obj_type)
    if not mapping:
        print(f"  错误: 不支持的导出类型 '{obj_type}'")
        return None

    _, file_extension = mapping

    payload = {
        "file_extension": file_extension,
        "token": obj_token,
        "type": obj_type,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == 0:
            ticket = data.get("data", {}).get("ticket")
            return ticket
        else:
            print(f"  创建导出任务失败: code={data.get('code')}, msg={data.get('msg')}")
            return None

    except requests.RequestException as e:
        print(f"  创建导出任务时网络请求失败: {e}")
        return None


def poll_export_task(ticket: str, obj_token: str, token: str) -> Optional[str]:
    """
    轮询导出任务状态，直到完成或超时。

    Args:
        ticket: 导出任务ID。
        obj_token: 原始文档的 obj_token。
        token: tenant_access_token。

    Returns:
        成功返回 file_token（用于下载），失败或超时返回 None。
    """
    url = f"https://open.feishu.cn/open-apis/drive/v1/export_tasks/{ticket}"
    headers = get_auth_header(token)

    for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                url, headers=headers, params={"token": obj_token}, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                print(f"  轮询导出任务失败: code={data.get('code')}, msg={data.get('msg')}")
                return None

            result = data.get("data", {}).get("result", {})
            job_status = result.get("job_status")

            if job_status == 0:
                # 导出成功
                file_token = result.get("file_token")
                return file_token
            elif job_status in (1, 2):
                # 初始化中 / 处理中
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            else:
                # 终态错误
                error_msg = result.get("job_error_msg", "未知错误")
                status_desc = {
                    3: "内部错误",
                    107: "文档过大",
                    108: "处理超时",
                    109: "内容块无权限",
                    110: "无权限",
                    111: "文档已删除",
                    122: "正在创建副本，无法导出",
                    123: "文档不存在",
                    6000: "文档图片过多",
                }.get(job_status, f"未知状态码 {job_status}")
                print(f"  导出任务失败: {status_desc} ({error_msg})")
                return None

        except requests.RequestException as e:
            print(f"  轮询导出任务时网络请求失败 (第{attempt}次): {e}")
            if attempt < POLL_MAX_ATTEMPTS:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            return None

    print(f"  导出任务轮询超时 (ticket: {ticket})，已达最大尝试次数 {POLL_MAX_ATTEMPTS}")
    return None


def download_exported_file(file_token: str, token: str) -> Optional[bytes]:
    """
    下载导出完成的文件（10分钟内必须下载）。

    Args:
        file_token: 导出文件的 file_token。
        token: tenant_access_token。

    Returns:
        成功返回文件二进制内容，失败返回 None。
    """
    url = f"https://open.feishu.cn/open-apis/drive/v1/export_tasks/file/{file_token}/download"
    headers = get_auth_header(token)

    try:
        response = requests.get(url, headers=headers, timeout=120)
        response.raise_for_status()
        return response.content

    except requests.RequestException as e:
        print(f"  下载导出文件失败: {e}")
        return None


def download_raw_file(obj_token: str, token: str) -> Optional[bytes]:
    """
    直接下载普通文件（obj_type="file"）。

    Args:
        obj_token: 文件的 obj_token。
        token: tenant_access_token。

    Returns:
        成功返回文件二进制内容，失败返回 None。
    """
    url = f"https://open.feishu.cn/open-apis/drive/v1/files/{obj_token}/download"
    headers = get_auth_header(token)

    try:
        response = requests.get(url, headers=headers, timeout=120)
        response.raise_for_status()
        return response.content

    except requests.RequestException as e:
        print(f"  直接下载文件失败: {e}")
        return None


def save_file(content: bytes, relative_path: str, source_dir: str) -> bool:
    """
    将文件内容保存到本地。

    Args:
        content: 文件二进制内容。
        relative_path: 相对路径（保持知识库目录结构）。
        source_dir: 根目标目录。

    Returns:
        成功返回 True，失败返回 False。
    """
    target_path = os.path.join(source_dir, relative_path)

    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(content)
        return True
    except (IOError, OSError) as e:
        print(f"  保存文件失败 '{relative_path}': {e}")
        return False


def download_cloud_doc(item: dict, token: str) -> bool:
    """
    下载云文档：创建导出任务 → 轮询完成 → 下载文件 → 保存。

    Args:
        item: 文件信息字典（path, obj_token, obj_type）。
        token: tenant_access_token。

    Returns:
        成功返回 True，失败返回 False。
    """
    obj_token = item["obj_token"]
    obj_type = item["obj_type"]
    path = item["path"]

    # 1. 创建导出任务
    ticket = create_export_task(obj_token, obj_type, token)
    if not ticket:
        return False

    time.sleep(REQUEST_INTERVAL_SECONDS)

    # 2. 轮询任务状态
    file_token = poll_export_task(ticket, obj_token, token)
    if not file_token:
        return False

    time.sleep(REQUEST_INTERVAL_SECONDS)

    # 3. 下载导出文件
    content = download_exported_file(file_token, token)
    if not content:
        return False

    # 4. 保存文件
    return save_file(content, path, SOURCE_DIR)


def download_regular_file(item: dict, token: str) -> bool:
    """
    直接下载普通文件（obj_type="file"）。

    Args:
        item: 文件信息字典（path, obj_token）。
        token: tenant_access_token。

    Returns:
        成功返回 True，失败返回 False。
    """
    obj_token = item["obj_token"]
    path = item["path"]

    # 1. 直接下载
    content = download_raw_file(obj_token, token)
    if not content:
        return False

    # 2. 保存文件
    return save_file(content, path, SOURCE_DIR)


def main(
    app_id=None,
    app_secret=None,
    files_to_download=None,
    source_dir=None,
    token=None,
):
    """
    主流程：读取下载列表 → 获取Token → 逐个下载文件。

    所有参数均可选，未传入时使用文件顶部的全局变量配置。
    可通过外部调用传参覆盖全局配置，也可直接修改全局变量后无参调用。

    Args:
        app_id: 飞书应用 App ID，默认使用全局 APP_ID。
        app_secret: 飞书应用 App Secret，默认使用全局 APP_SECRET。
        files_to_download: 下载列表文件路径，默认使用全局 FILES_TO_DOWNLOAD。
        source_dir: 下载目标目录，默认使用全局 SOURCE_DIR。
        token: 已有的 tenant_access_token，传入后跳过自动获取。
    """
    # 将传入参数同步到全局变量，供 download_cloud_doc/download_regular_file 读取
    global FILES_TO_DOWNLOAD, SOURCE_DIR

    # 参数回退到全局变量
    app_id = app_id or APP_ID
    app_secret = app_secret or APP_SECRET
    files_to_download = files_to_download or FILES_TO_DOWNLOAD
    source_dir = source_dir or SOURCE_DIR

    FILES_TO_DOWNLOAD = files_to_download
    SOURCE_DIR = source_dir

    # 1. 读取下载列表
    try:
        with open(files_to_download, "r", encoding="utf-8") as f:
            files_list = json.load(f)
    except FileNotFoundError:
        print(f"错误: 下载列表文件 '{files_to_download}' 未找到。请先运行 feishu_get_kb_files.py。")
        return
    except json.JSONDecodeError:
        print(f"错误: 解析下载列表文件 '{files_to_download}' 失败。")
        return

    if not files_list:
        print("下载列表为空，无需下载。")
        return

    total = len(files_list)
    print(f"共 {total} 个文件需要下载。")

    # 2. 获取 tenant_access_token
    if not token:
        token = get_feishu_tenant_access_token(app_id, app_secret)
    if not token:
        print("错误: 无法获取飞书访问凭证，程序退出。")
        return
    token_acquired_time = time.time()

    # 3. 创建目标目录
    os.makedirs(source_dir, exist_ok=True)

    # 4. 逐个下载文件
    success = 0
    failed = 0
    skipped = 0

    for i, item in enumerate(files_list, 1):
        path = item.get("path", "")
        obj_type = item.get("obj_type", "")

        print(f"\n[{i}/{total}] 下载: {path}")

        # 检查是否已存在（支持断点续传）
        target_path = os.path.join(source_dir, path)
        if os.path.exists(target_path):
            print(f"  [跳过] 文件已存在: {path}")
            skipped += 1
            continue

        # 检查 token 是否需要刷新（>110分钟）
        if time.time() - token_acquired_time > 6600:
            print("  Token 即将过期，正在刷新...")
            new_token = get_feishu_tenant_access_token(app_id, app_secret)
            if new_token:
                token = new_token
                token_acquired_time = time.time()
                print("  Token 已刷新。")
            else:
                print("  警告: Token 刷新失败，继续使用旧 Token。")

        # 根据类型选择下载方式
        if obj_type in OBJ_TYPE_EXPORT_MAP:
            ok = download_cloud_doc(item, token)
        elif obj_type == "file":
            ok = download_regular_file(item, token)
        else:
            print(f"  [跳过] 不支持的文件类型: {obj_type}")
            skipped += 1
            continue

        if ok:
            success += 1
            print(f"  [成功] {path}")
        else:
            failed += 1
            print(f"  [失败] {path} (obj_token: {item.get('obj_token', '')})")

        # API调用间隔
        time.sleep(REQUEST_INTERVAL_SECONDS)

    # 5. 打印统计
    print(f"\n--- 下载统计 ---")
    print(f"总数: {total}")
    print(f"成功: {success}")
    print(f"失败: {failed}")
    print(f"跳过: {skipped}")
    print("\n下载任务完成！")


if __name__ == "__main__":
    main()
