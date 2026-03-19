# -*- coding: utf-8 -*-

"""
本程序用于遍历飞书知识库中的所有文件，与本地NAS文件树进行对比，
生成差异列表供后续下载使用。

工作流程:
1. 获取飞书 tenant_access_token。
2. 调用飞书开放平台API获取知识空间列表，查找目标空间。
3. 从根节点开始，递归遍历知识空间的所有子节点。
4. 扫描本地NAS文件夹，生成文件树。
5. 对比知识库文件树与NAS文件树，生成需要下载的文件列表。
6. 输出: kb_tree.json（完整结构）+ files_to_download.json（需下载的文件）。

使用前请确保:
- 已安装 requests 库: `pip install requests`
"""

import os
import json
import time
import datetime
import requests
from typing import List, Dict, Optional

from feishu.get_token import get_feishu_tenant_access_token

# ============================================================
# 基础配置
# ============================================================
APP_ID = ""  # 飞书应用 App ID
APP_SECRET = ""  # 飞书应用 App Secret
SPACE_NAME = ""  # 需要遍历的目标知识空间的完整名称
NAS_ROOT_PATH = ""  # 要对比的本地NAS文件夹根路径
KB_TREE_OUTPUT_FILE = "kb_tree.json"  # 存储知识库完整文件树的JSON文件
FILES_TO_DOWNLOAD_OUTPUT = "files_to_download.json"  # 存储需要下载的文件列表
SPACE_LIST_OUTPUT_FILE = "space_list.json"  # 存储获取的知识空间列表
# ============================================================

# ============================================================
# 白名单配置
# ============================================================
# 指定需要同步的子文件夹路径（相对于知识空间根目录）
# 格式："知识空间名称":["需要同步的路径列表"]
# ============================================================
SYNC_FILTERS = {
    "知识空间名称": ["子目录路径1"],
    # 可以添加更多知识空间和对应的同步路径
}

# 如果设置为True，则只同步SYNC_FILTERS中指定的路径
# 如果设置为False或知识空间不在SYNC_FILTERS中，则同步整个知识空间
USE_SYNC_FILTER = True
# ============================================================

# ============================================================
# 黑名单配置
# ============================================================
# 在此列表中添加需要排除的文件或文件夹路径（相对于知识空间根目录）
# 支持精确匹配和目录递归排除（黑名单目录时，其下所有内容也排除）
# 黑名单优先级高于白名单
# ============================================================
BLACKLIST = [
    # 示例：
    # "临时文件",
    # "废弃文档/旧版本",
]

# 文件扩展名黑名单
# 在此列表中添加需要排除的文件扩展名（带点号前缀）
# 匹配到黑名单扩展名的文件将被跳过，不会加入同步列表
# ============================================================
FILE_EXTENSION_BLACKLIST = [
    ".zip",
    ".mp4",
    ".exe",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".avi",
    ".mov",
    ".mkv",
    # 可以继续添加其他需要排除的扩展名
]
# ============================================================

# ============================================================
# 飞书 obj_type 映射配置
# ============================================================
# 将飞书节点的 obj_type 映射到: (输出文件扩展名, 导出API的file_extension参数)
# "file" 类型无需转换，扩展名取节点 title 本身
# "slides" 和 "mindnote" 飞书导出API暂不支持，将跳过
# ============================================================
OBJ_TYPE_EXPORT_MAP = {
    "docx": (".docx", "docx"),    # 新版飞书文档 → 导出为 docx
    "doc": (".docx", "docx"),     # 旧版飞书文档 → 导出为 docx
    "sheet": (".xlsx", "xlsx"),   # 电子表格 → 导出为 xlsx
    "bitable": (".xlsx", "xlsx"), # 多维表格 → 导出为 xlsx
    "file": (None, None),         # 普通上传文件，扩展名取 title 本身
}

# 不支持导出的 obj_type 列表（跳过并打印警告）
UNSUPPORTED_OBJ_TYPES = {"slides", "mindnote"}
# ============================================================

# API速率限制：飞书 wiki/drive API 限制 100次/分钟
API_REQUEST_INTERVAL = 0.7  # 每次API调用后的等待时间（秒），约85次/分钟


def get_auth_header(token: str) -> dict:
    """返回飞书API认证请求头。"""
    return {"Authorization": f"Bearer {token}"}


def get_space_list(token: str) -> List[Dict]:
    """
    调用飞书API，获取当前应用可访问的知识空间列表（处理分页）。

    Args:
        token: tenant_access_token

    Returns:
        包含所有知识空间信息的列表。
    """
    url = "https://open.feishu.cn/open-apis/wiki/v2/spaces"
    headers = get_auth_header(token)
    all_spaces = []
    page_token = None

    while True:
        params = {"page_size": 50}
        if page_token:
            params["page_token"] = page_token

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                print(f"获取知识空间列表失败: code={data.get('code')}, msg={data.get('msg')}")
                break

            items = data.get("data", {}).get("items", [])
            if items:
                all_spaces.extend(items)

            has_more = data.get("data", {}).get("has_more", False)
            if has_more:
                page_token = data.get("data", {}).get("page_token")
            else:
                break

        except requests.RequestException as e:
            print(f"获取知识空间列表时网络请求失败: {e}")
            break

        time.sleep(API_REQUEST_INTERVAL)

    return all_spaces


def find_space_id(space_name: str, token: str) -> Optional[str]:
    """
    从知识空间列表中查找指定名称的空间，返回其 space_id。

    Args:
        space_name: 知识空间名称。
        token: tenant_access_token。

    Returns:
        找到则返回 space_id，否则返回 None。
    """
    print("正在从API获取知识空间列表...")
    spaces = get_space_list(token)

    # 将知识空间列表写入文件
    if spaces:
        try:
            with open(SPACE_LIST_OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(spaces, f, ensure_ascii=False, indent=4)
            print(f"知识空间列表已成功写入到 '{SPACE_LIST_OUTPUT_FILE}'")
        except IOError as e:
            print(f"错误: 无法写入文件 '{SPACE_LIST_OUTPUT_FILE}': {e}")

    for space in spaces:
        if space.get("name") == space_name:
            space_id = space.get("space_id")
            print(f"成功找到知识空间 '{space_name}' (space_id: {space_id})")
            return space_id

    print(f"错误: 未找到名为 '{space_name}' 的知识空间。")
    return None


def get_child_nodes(space_id: str, parent_node_token: Optional[str], token: str) -> List[Dict]:
    """
    调用飞书API，获取指定父节点下的所有子节点（处理分页）。

    Args:
        space_id: 知识空间ID。
        parent_node_token: 父节点token，None表示获取根节点的子节点。
        token: tenant_access_token。

    Returns:
        包含子节点信息的列表。
    """
    url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
    headers = get_auth_header(token)
    all_nodes = []
    page_token = None

    while True:
        params = {"page_size": 50}
        if page_token:
            params["page_token"] = page_token
        if parent_node_token:
            params["parent_node_token"] = parent_node_token

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                print(f"获取子节点列表失败: code={data.get('code')}, msg={data.get('msg')}")
                break

            items = data.get("data", {}).get("items", [])
            if items:
                all_nodes.extend(items)

            has_more = data.get("data", {}).get("has_more", False)
            if has_more:
                page_token = data.get("data", {}).get("page_token")
            else:
                break

        except requests.RequestException as e:
            print(f"获取子节点列表时网络请求失败: {e}")
            break

        time.sleep(API_REQUEST_INTERVAL)

    return all_nodes


def _is_blacklisted(current_path: str, blacklist: list) -> bool:
    """
    检查路径是否在黑名单中。
    支持精确匹配和目录前缀匹配（黑名单目录时，其下所有内容也排除）。

    :param current_path: 当前路径
    :param blacklist: 黑名单列表（相对路径列表）
    :return: True 表示在黑名单中，False 表示不在黑名单中
    """
    for item in blacklist:
        # 精确匹配
        if current_path == item:
            return True
        # 检查当前路径是否是黑名单目录下的文件/子目录
        if current_path.startswith(item + "/"):
            return True
    return False


def _should_traverse(current_path: str, space_name: str) -> bool:
    """
    检查路径是否应该被遍历（白名单过滤）。
    当启用白名单过滤时，只遍历SYNC_FILTERS中指定的路径及其父目录和子目录。

    :param current_path: 当前路径
    :param space_name: 当前知识空间名称
    :return: True 表示应该遍历，False 表示应该跳过
    """
    if not USE_SYNC_FILTER or space_name not in SYNC_FILTERS:
        return True

    include_paths = SYNC_FILTERS[space_name]
    for include_path in include_paths:
        # 匹配条件：
        # 1. 当前路径就是目标路径
        # 2. 当前路径是目标路径的子目录
        # 3. 当前路径是目标路径的父目录（需要进入才能到达目标）
        if (
            current_path == include_path
            or current_path.startswith(include_path + "/")
            or include_path.startswith(current_path + "/")
        ):
            return True

    return False


def _resolve_file_path(title: str, obj_type: str) -> Optional[str]:
    """
    根据节点标题和 obj_type，返回最终的文件名（带正确扩展名）。

    对于普通文件 (obj_type="file")，扩展名取 title 本身。
    对于云文档类型，根据 OBJ_TYPE_EXPORT_MAP 添加/替换扩展名。
    对于不支持导出的类型，返回 None。

    :param title: 节点标题
    :param obj_type: 飞书节点类型
    :return: 文件名字符串，或 None（不支持的类型）
    """
    if obj_type in UNSUPPORTED_OBJ_TYPES:
        return None

    if obj_type == "file":
        # 普通文件，title 本身就包含扩展名
        return title

    mapping = OBJ_TYPE_EXPORT_MAP.get(obj_type)
    if mapping is None:
        return None

    target_ext, _ = mapping
    if target_ext is None:
        return title

    # 云文档：去除 title 中可能存在的扩展名，添加目标扩展名
    name, _ = os.path.splitext(title)
    return name + target_ext


def traverse_space_nodes(
    space_id: str,
    parent_node_token: Optional[str],
    token: str,
    parent_path: str,
    kb_tree: dict,
):
    """
    递归遍历飞书知识空间的所有节点，构建文件树。
    支持根据SYNC_FILTERS配置只同步指定的文件夹。

    Args:
        space_id: 知识空间ID。
        parent_node_token: 父节点token，None表示从根节点开始。
        token: tenant_access_token。
        parent_path: 父节点的路径。
        kb_tree: 用于存储文件树的字典（就地修改）。
    """
    nodes = get_child_nodes(space_id, parent_node_token, token)
    if not nodes:
        return

    for node in nodes:
        obj_type = node.get("obj_type", "")
        title = node.get("title", "未命名")
        node_token = node.get("node_token", "")
        obj_token = node.get("obj_token", "")
        has_child = node.get("has_child", False)
        obj_edit_time = node.get("obj_edit_time", "")

        # 替换路径中可能存在的无效字符
        safe_title = title.replace("/", "_").replace("\\", "_")
        current_path = f"{parent_path}/{safe_title}" if parent_path else safe_title

        # --- 白名单过滤 ---
        if not _should_traverse(current_path, SPACE_NAME):
            print(f"  [跳过] 路径 '{current_path}' 不在同步列表中")
            continue

        # --- 黑名单检查 ---
        if _is_blacklisted(current_path, BLACKLIST):
            print(f"  [黑名单跳过] 路径 '{current_path}' 在黑名单中")
            continue

        print(f"  正在处理知识库节点: {current_path} (类型: {obj_type})")

        # 不支持导出的类型：打印警告
        if obj_type in UNSUPPORTED_OBJ_TYPES:
            print(f"  [警告] 节点 '{current_path}' 的类型 '{obj_type}' 暂不支持导出，已跳过")
            # 仍然递归子节点（slides/mindnote 下可能有子文档）
            if has_child:
                traverse_space_nodes(space_id, node_token, token, current_path, kb_tree)
            continue

        # 解析文件路径
        file_name = _resolve_file_path(title, obj_type)
        if file_name is not None:
            # 构造最终路径
            final_path = f"{parent_path}/{file_name}" if parent_path else file_name

            # --- 检查文件扩展名黑名单 ---
            _, ext = os.path.splitext(final_path)
            if ext.lower() in FILE_EXTENSION_BLACKLIST:
                print(f"  [扩展名黑名单跳过] 文件 '{final_path}' 扩展名 '{ext}' 在黑名单中")
            else:
                # 将 obj_edit_time（Unix时间戳字符串）转换为 ISO 8601 格式
                try:
                    timestamp = int(obj_edit_time) if obj_edit_time else 0
                    modified_time_iso = (
                        datetime.datetime.fromtimestamp(timestamp).isoformat(
                            timespec="seconds"
                        )
                        + "Z"
                    )
                except (ValueError, OSError):
                    modified_time_iso = ""

                kb_tree[final_path] = {
                    "modifiedTime": modified_time_iso,
                    "obj_token": obj_token,
                    "obj_type": obj_type,
                    "space_id": space_id,
                }

        # 递归遍历子节点（飞书中某些文档节点也可能有子节点）
        if has_child:
            traverse_space_nodes(space_id, node_token, token, current_path, kb_tree)


def get_nas_file_tree(nas_root_path: str) -> dict:
    """
    生成NAS文件夹的文件树结构。

    Args:
        nas_root_path: NAS根目录路径。

    Returns:
        文件树字典: {相对路径: {modifiedTime, path}}
    """
    print(f"\n正在扫描本地NAS文件夹: {nas_root_path}")
    file_tree = {}
    if not os.path.isdir(nas_root_path):
        print(
            f"警告: 本地NAS路径 '{nas_root_path}' 不存在或不是一个目录。将视为空文件夹。"
        )
        return file_tree

    for root, _, files in os.walk(nas_root_path):
        for file in files:
            file_path = os.path.join(root, file)
            # 使用os.path.normpath来规范化路径分隔符
            relative_path = os.path.normpath(os.path.relpath(file_path, nas_root_path))
            # 将Windows路径分隔符'\'统一替换为'/'
            relative_path = relative_path.replace("\\", "/")

            modified_time = os.path.getmtime(file_path)
            # 将时间戳转换为ISO 8601格式字符串
            modified_time_iso = (
                datetime.datetime.fromtimestamp(modified_time).isoformat(
                    timespec="seconds"
                )
                + "Z"
            )

            file_tree[relative_path] = {
                "modifiedTime": modified_time_iso,
                "path": file_path,
            }
    print("本地NAS文件夹扫描完成。")
    return file_tree


def compare_trees_and_get_downloads(kb_tree: dict, nas_tree: dict) -> List[Dict]:
    """
    比较知识库和NAS的文件树，返回需要下载的文件描述列表。

    与钉钉版不同，飞书没有直接下载URL，返回的是包含
    obj_token、obj_type、space_id 等信息的字典列表。

    Args:
        kb_tree: 知识库文件树。
        nas_tree: NAS文件树。

    Returns:
        需要下载的文件信息列表。
    """
    print("\n正在比较知识库与本地NAS文件...")
    files_to_download = []

    for kb_path, kb_info in kb_tree.items():
        if kb_path not in nas_tree:
            print(f"[新增] 文件 '{kb_path}' 在本地不存在，准备下载。")
            files_to_download.append({
                "path": kb_path,
                "obj_token": kb_info["obj_token"],
                "obj_type": kb_info["obj_type"],
                "space_id": kb_info["space_id"],
            })
        else:
            # 文件已存在，比较修改时间
            try:
                nas_time_str = (
                    nas_tree[kb_path]["modifiedTime"].split(".")[0].replace("Z", "")
                )
                kb_time_str = kb_info["modifiedTime"].split(".")[0].replace("Z", "")

                nas_time = datetime.datetime.fromisoformat(nas_time_str)
                kb_time = datetime.datetime.fromisoformat(kb_time_str)

                if kb_time > nas_time:
                    print(
                        f"[更新] 文件 '{kb_path}' 在知识库中已更新，准备下载。 "
                        f"(知识库: {kb_time} > 本地: {nas_time})"
                    )
                    files_to_download.append({
                        "path": kb_path,
                        "obj_token": kb_info["obj_token"],
                        "obj_type": kb_info["obj_type"],
                        "space_id": kb_info["space_id"],
                    })
            except (ValueError, KeyError) as e:
                print(
                    f"警告: 处理文件 '{kb_path}' 的时间戳时出错: {e}。将默认下载该文件。"
                )
                files_to_download.append({
                    "path": kb_path,
                    "obj_token": kb_info["obj_token"],
                    "obj_type": kb_info["obj_type"],
                    "space_id": kb_info["space_id"],
                })

    print("文件比较完成。")
    return files_to_download


def main(
    app_id=None,
    app_secret=None,
    space_name=None,
    nas_root_path=None,
    kb_tree_output_file=None,
    files_to_download_output=None,
    space_list_output_file=None,
    token=None,
):
    """
    主流程：获取Token → 查找空间 → 遍历 → 对比NAS → 输出JSON。

    所有参数均可选，未传入时使用文件顶部的全局变量配置。
    可通过外部调用传参覆盖全局配置，也可直接修改全局变量后无参调用。

    Args:
        app_id: 飞书应用 App ID，默认使用全局 APP_ID。
        app_secret: 飞书应用 App Secret，默认使用全局 APP_SECRET。
        space_name: 目标知识空间名称，默认使用全局 SPACE_NAME。
        nas_root_path: 本地NAS文件夹根路径，默认使用全局 NAS_ROOT_PATH。
        kb_tree_output_file: kb_tree.json 输出路径，默认使用全局 KB_TREE_OUTPUT_FILE。
        files_to_download_output: 下载列表输出路径，默认使用全局 FILES_TO_DOWNLOAD_OUTPUT。
        space_list_output_file: 知识空间列表输出路径，默认使用全局 SPACE_LIST_OUTPUT_FILE。
        token: 已有的 tenant_access_token，传入后跳过自动获取。
    """
    # 将传入的参数同步到全局变量，供 traverse_space_nodes 等函数读取
    global SPACE_NAME, SPACE_LIST_OUTPUT_FILE

    # 参数回退到全局变量
    app_id = app_id or APP_ID
    app_secret = app_secret or APP_SECRET
    space_name = space_name or SPACE_NAME
    nas_root_path = nas_root_path or NAS_ROOT_PATH
    kb_tree_output_file = kb_tree_output_file or KB_TREE_OUTPUT_FILE
    files_to_download_output = files_to_download_output or FILES_TO_DOWNLOAD_OUTPUT
    space_list_output_file = space_list_output_file or SPACE_LIST_OUTPUT_FILE

    SPACE_NAME = space_name
    SPACE_LIST_OUTPUT_FILE = space_list_output_file

    # 1. 获取 tenant_access_token（如果外部未传入）
    if not token:
        token = get_feishu_tenant_access_token(app_id, app_secret)
    if not token:
        print("错误: 无法获取飞书访问凭证，程序退出。")
        return

    # 2. 查找目标知识空间
    space_id = find_space_id(space_name, token)
    if not space_id:
        print(f"错误: 无法找到名为 '{space_name}' 的知识空间。请检查名称是否正确。")
        return

    # 3. 遍历知识空间，构建文件树
    print(f"\n开始遍历知识空间: '{space_name}' (space_id: {space_id})")
    kb_tree = {}
    traverse_space_nodes(space_id, None, token, "", kb_tree)
    print("知识空间遍历完成。")

    # 4. 将完整的知识库文件树写入JSON文件
    try:
        with open(kb_tree_output_file, "w", encoding="utf-8") as f:
            json.dump(kb_tree, f, ensure_ascii=False, indent=4)
        print(f"完整的知识库文件树已成功写入到 '{kb_tree_output_file}'")
    except IOError as e:
        print(f"错误: 无法写入知识库文件树 '{kb_tree_output_file}': {e}")

    # 5. 获取NAS文件树
    nas_tree = get_nas_file_tree(nas_root_path)

    # 6. 比较文件树并获取需要下载的文件
    files_to_download = compare_trees_and_get_downloads(kb_tree, nas_tree)

    # 7. 将需要下载的文件列表写入JSON
    if files_to_download:
        print(f"\n--- 发现 {len(files_to_download)} 个文件需要下载 ---")
        try:
            with open(files_to_download_output, "w", encoding="utf-8") as f:
                json.dump(files_to_download, f, ensure_ascii=False, indent=4)
            print(f"需要下载的文件列表已成功写入到 '{files_to_download_output}'")
        except IOError as e:
            print(f"错误: 无法写入下载列表 '{files_to_download_output}': {e}")
    else:
        print("\n--- 所有文件都是最新的，无需下载。 ---")

    # 8. 打印统计信息
    print(f"\n--- 统计 ---")
    print(f"知识库文件总数: {len(kb_tree)}")
    print(f"NAS文件总数: {len(nas_tree)}")
    print(f"需要下载的文件数: {len(files_to_download)}")
    print("\n任务完成！")


if __name__ == "__main__":
    main()
