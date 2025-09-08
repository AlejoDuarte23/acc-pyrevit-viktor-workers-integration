import requests
import base64
import urllib.parse
import viktor as vkt

from concurrent.futures import ThreadPoolExecutor, as_completed
from app.models.hubs import HubsList
from app.models.projects import ProjectsList
from app.models.folders import FoldersList
from app.models.contents import FolderContentsList


APS_BASE_URL = "https://developer.api.autodesk.com"

def get_hubs(token) -> HubsList:
    """
    Retrieves a list of hubs the user has access to.
    Corresponds to: GET /project/v1/hubs
    """
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{APS_BASE_URL}/project/v1/hubs", headers=headers)
    response.raise_for_status()
    hubs_data = HubsList.model_validate_json(response.text)  # type: ignore[attr-defined]
    return hubs_data

def get_projects(hub_id, token) -> ProjectsList:
    """
    Retrieves a list of projects within a specific hub.
    Corresponds to: GET /project/v1/hubs/{hub_id}/projects
    """
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{APS_BASE_URL}/project/v1/hubs/{hub_id}/projects", headers=headers)
    response.raise_for_status()
    return ProjectsList.model_validate_json(response.text)  # type: ignore[attr-defined]

def get_top_folders(hub_id, project_id, token) -> FoldersList:
    """
    Retrieves the top-level folders of a project.
    Corresponds to: GET /project/v1/hubs/{hub_id}/projects/{project_id}/topFolders
    """
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{APS_BASE_URL}/project/v1/hubs/{hub_id}/projects/{project_id}/topFolders", headers=headers)
    response.raise_for_status()
    return FoldersList.model_validate_json(response.text)  # type: ignore[attr-defined]


def get_folder_contents(project_id, folder_id, token) -> FolderContentsList:
    """
    Retrieves the contents (files and subfolders) of a specific folder.
    Corresponds to: GET /data/v1/projects/{project_id}/folders/{folder_id}/contents
    """
    headers = {"Authorization": f"Bearer {token}"}
    encoded_folder_id = urllib.parse.quote(folder_id) # URL-encode the ID
    url = f"https://developer.api.autodesk.com/data/v1/projects/{project_id}/folders/{encoded_folder_id}/contents"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return FolderContentsList.model_validate_json(response.text)  # type: ignore[attr-defined]

def get_item_versions(project_id, item_id, token):
    """
    Retrieves all versions of a specific item (file).
    response.raise_for_status()

    Corresponds to: GET /data/v1/projects/{project_id}/items/{item_id}/versions
    """
    headers = {"Authorization": f"Bearer {token}"}
    encoded_item_id = urllib.parse.quote(item_id) # URL-encode the ID
    url = f"https://developer.api.autodesk.com/data/v1/projects/{project_id}/items/{encoded_item_id}/versions"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get("data", [])


def get_hub_names(token):
    """Return a list of hub names for the given token."""
    hubs = get_hubs(token)
    if hubs and hasattr(hubs, "data"):
        return [hub.attributes.name for hub in hubs.data]
    return []


def get_hub_id_by_name(token, hub_name):
    """Return hub ID for a given hub name."""
    hubs = get_hubs(token)
    if hubs and hasattr(hubs, "data"):
        for hub in hubs.data:
            if getattr(hub.attributes, "name", None) == hub_name:
                return hub.id
    return None

def get_all_cad_file_from_hub(
    token: str,
    hub_id: str | None = None,
    *,
    include_views: bool = False,
    max_workers: int = 12,
) -> dict[str, dict[str, str]]:
    """
    Walk through the Autodesk APS hub structure and collect viewable CAD files.

    Returns a dict mapping display_name -> {
        "urn": <latest_version_urn>,
        "project_id": <project_id>,
        "item_id": <item_id>,
        "folder_id": <containing_folder_id>
    }
    Always returns a dict (possibly empty).
    """

    def process_top_folder(project_id_with_prefix: str, folder_id: str, executor: ThreadPoolExecutor) -> dict[str, dict[str, str]]:
        """Worker to crawl a top folder (and its subtree)."""
        return (
            get_all_cad_from_folder(
                project_id_with_prefix,
                folder_id,
                token,
                indent="    ",
                include_views=include_views,
                executor=executor,
            )
            or {}
        )

    def process_hub(_hub_id: str, executor: ThreadPoolExecutor) -> dict[str, dict[str, str]]:
        hub_viewables: dict[str, dict[str, str]] = {}
        projects = get_projects(_hub_id, token)
        if projects and projects.data:
            for project in projects.data:
                project_id_with_prefix = project.id  # already prefixed (e.g., "b.")
                top_folders = get_top_folders(_hub_id, project_id_with_prefix, token)
                if top_folders and top_folders.data:
                    futures = [
                        executor.submit(process_top_folder, project_id_with_prefix, folder.id, executor)
                        for folder in top_folders.data
                    ]
                    for fut in as_completed(futures):
                        try:
                            viewables = fut.result()
                            if viewables:
                                hub_viewables.update(viewables)
                        except Exception:
                            pass
        return hub_viewables

    # Determine which hubs to process
    hub_ids: list[str]
    if hub_id:
        hub_ids = [hub_id]
    else:
        hubs = get_hubs(token)
        if not hubs or not hubs.data:
            return {}
        hub_ids = [h.id for h in hubs.data]

    # Execute concurrently across hubs and folders
    all_viewables: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        hub_futures = {executor.submit(process_hub, _hid, executor): _hid for _hid in hub_ids}
        for fut in as_completed(hub_futures):
            try:
                hub_result = fut.result()
                if hub_result:
                    all_viewables.update(hub_result)
            except Exception:
                pass

    return all_viewables


def get_all_cad_from_folder(
    project_id,
    folder_id,
    token,
    indent="",
    *,
    include_views: bool = False,
    executor: ThreadPoolExecutor | None = None,
):
    """
    Recursively traverses a folder and its subfolders. If an executor is provided,
    subfolders and items are processed concurrently; otherwise, processed serially.

    Returns a dict mapping display_name -> metadata including:
        urn, project_id, item_id, folder_id
    """
    viewable_files: dict[str, dict[str, str]] = {}

    try:
        contents = get_folder_contents(project_id, folder_id, token)
    except requests.exceptions.HTTPError:
        return viewable_files  # silent: return empty on access errors

    if not contents.data:
        return viewable_files

    # Helpers for item and folder processing
    def process_item(content) -> dict[str, dict[str, str]]:
        try:
            display_name = content.attributes.displayName
            content_id = content.id
            supported_extensions = [
                ".rvt",
                ".dwg",
                ".ifc",
                ".step",
                ".stp",
                ".iam",
                ".ipt",
            ]
            if not any(display_name.lower().endswith(ext) for ext in supported_extensions):
                return {}
            versions = get_item_versions(project_id, content_id, token)
            if not versions:
                return {}
            latest_version = versions[0]
            version_urn = latest_version["id"]

            if include_views:
                # Placeholder for optional view / metadata enrichment. Implementation removed
                # because get_model_views_and_metadata is not defined in this module.
                pass
            return {
                display_name: {
                    "urn": version_urn,
                    "project_id": project_id,
                    "item_id": content_id,
                    "folder_id": folder_id,
                }
            }
        except Exception:
            return {}

    def process_folder(content) -> dict[str, dict[str, str]]:
        try:
            return get_all_cad_from_folder(
                project_id,
                content.id,
                token,
                indent + "  ",
                include_views=include_views,
                executor=executor,
            )
        except Exception:
            return {}

    if executor is None:
        # Serial path
        for content in contents.data:
            try:
                content_type = content.type  # 'folders' or 'items'
                if content_type == "folders":
                    sub_viewables = process_folder(content)
                    if sub_viewables:
                        viewable_files.update(sub_viewables)
                elif content_type == "items":
                    item_result = process_item(content)
                    if item_result:
                        viewable_files.update(item_result)
            except Exception:
                continue
        return viewable_files

    # Concurrent path using provided executor
    futures = []
    for content in contents.data:
        try:
            if content.type == "folders":
                futures.append(executor.submit(process_folder, content))
            elif content.type == "items":
                futures.append(executor.submit(process_item, content))
        except Exception:
            continue

    for fut in as_completed(futures):
        try:
            res = fut.result()
            if res:
                viewable_files.update(res)
        except Exception:
            continue

    return viewable_files



def download_file_content(storage_urn, token):
    """
    Downloads the actual content of a file from OSS given its storage URN.
    """
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Parse the URN to get the bucket key and object key
    # Example URN: "urn:adsk.objects:os.object:wip.dm.prod/abcdef.ifc"
    urn_parts = storage_urn.split(':')
    object_id = urn_parts[-1]
    bucket_key, object_key = object_id.split('/')
    
    encoded_bucket_key = urllib.parse.quote(bucket_key)
    encoded_object_key = urllib.parse.quote(object_key)

    # 2. Get a temporary, signed S3 URL to download the file directly
    # This is the most efficient method as it bypasses APS servers for the download.
    s3_url_endpoint = f"{APS_BASE_URL}/oss/v2/buckets/{encoded_bucket_key}/objects/{encoded_object_key}/signeds3download"
    
    s3_response = requests.get(s3_url_endpoint, headers=headers)
    s3_response.raise_for_status()
    s3_data = s3_response.json()
    
    # The response will contain a URL to download from. If the object was uploaded in chunks
    # it might contain multiple URLs. For most ACC files, it will be one.
    download_url = s3_data.get('url')
    if not download_url:
        raise ValueError("Could not retrieve the S3 download URL from APS.")

    # 3. Use the S3 URL to get the file content
    # Note: No auth headers are needed for the S3 URL itself.
    file_response = requests.get(download_url)
    file_response.raise_for_status()
    
    # The content is in binary format
    return file_response.content

def get_file_content(token: str, project_id: str, item_id: str) -> bytes:
    """
    Wrapper to get raw binary content of a file given navigation names.
    """
    versions = get_item_versions(project_id, item_id, token)
    if not versions:
        raise ValueError("No versions found for this item")
    latest_version = versions[0]
    storage_urn = latest_version.get("relationships", {}).get("storage", {}).get("data", {}).get("id")
    if not storage_urn:
        raise ValueError("Could not find storage location for this version")
    file_content = download_file_content(storage_urn, token)
    return file_content 

def list_cad_views(token: str, urn: str) -> list[str] | list[vkt.OptionListElement]:
        encoded_urn = base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")
        url = f"https://developer.api.autodesk.com/modelderivative/v2/designdata/{encoded_urn}/manifest"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            manifest = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching manifest: {e}")
            return ["Error fetching manifest"]

        options = []
        # Find the main derivative with viewable geometry
        for derivative in manifest.get("derivatives", []):
            if derivative.get("outputType") in ["svf", "svf2"]:
                # Find the parent geometry nodes for both 3D and 2D
                for geometry_node in derivative.get("children", []):
                    if geometry_node.get("type") == "geometry" and geometry_node.get(
                        "role"
                    ) in ["3d", "2d"]:
                        view_name = geometry_node.get("name")
                        view_guid = None
                        view_role = geometry_node.get("role")  # '3d' or '2d'

                        # Search its children for the actual node with "type": "view"
                        for child_node in geometry_node.get("children", []):
                            if child_node.get("type") == "view":
                                view_guid = child_node.get("guid")
                                if child_node.get("name").startswith("Sheet:"):
                                    view_name = child_node.get("name")
                                break  # Found the correct view node

                        if view_name and view_guid:
                            # I added this prefix but can be ommited
                            label_prefix = "[3D]" if view_role == "3d" else "[2D]"
                            options.append(
                                vkt.OptionListElement(
                                    label=f"{label_prefix} {view_name}", value=view_guid
                                )
                            )
        return options