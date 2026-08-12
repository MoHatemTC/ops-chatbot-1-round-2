import requests

from api.config import BASE_URL


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_cohorts(token, include_disabled=False):
    response = requests.get(
        f"{BASE_URL}/kb/cohorts",
        headers=_auth_headers(token),
        params={"include_disabled": include_disabled},
    )
    response.raise_for_status()
    return response.json()["cohorts"]


def get_cohort_detail(token, cohort_id):
    response = requests.get(
        f"{BASE_URL}/kb/cohorts/{cohort_id}",
        headers=_auth_headers(token),
    )
    response.raise_for_status()
    return response.json()


def create_cohort(
    token,
    *,
    name,
    materials_root=None,
    description=None,
    project=None,
    start_date=None,
    end_date=None,
    enabled=True,
):
    payload = {
        "name": name,
        "materials_root": materials_root,
        "description": description,
        "project": project,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "enabled": enabled,
    }
    response = requests.post(
        f"{BASE_URL}/kb/cohorts",
        headers=_auth_headers(token),
        json=payload,
        timeout=15,
    )
    if not response.ok:
        raise CohortAPIError(_extract_error(response))
    return response.json()


def update_cohort(token, cohort_id, **fields):
    response = requests.patch(
        f"{BASE_URL}/kb/cohorts/{cohort_id}",
        headers=_auth_headers(token),
        json=fields,
        timeout=15,
    )
    if not response.ok:
        raise CohortAPIError(_extract_error(response))
    return response.json()


def delete_cohort(token, cohort_id, delete_files=False):
    response = requests.delete(
        f"{BASE_URL}/kb/cohorts/{cohort_id}",
        params={"delete_files": delete_files},
        headers={"Authorization": f"Bearer {token}"}
    )

    response.raise_for_status()

    if response.status_code == 204:
        return {"success": True}

    return response.json()

def upload_material(token, cohort_id, *, title, material_type, file_name, file_bytes):
    response = requests.post(
        f"{BASE_URL}/kb/cohorts/{cohort_id}/materials",
        headers=_auth_headers(token),
        data={"title": title, "material_type": material_type},
        files={"file": (file_name, file_bytes)},
    )
    if not response.ok:
        raise CohortAPIError(_extract_error(response))
    return response.json()


def remove_material(token, cohort_id, source, delete_file=False):
    response = requests.delete(
        f"{BASE_URL}/kb/cohorts/{cohort_id}/materials/{source}",
        headers=_auth_headers(token),
        params={"delete_file": delete_file},
    )
    if not response.ok:
        raise CohortAPIError(_extract_error(response))
    return response.json()


class CohortAPIError(Exception):
    """Raised when the cohorts API returns a non-2xx response."""


def _extract_error(response):
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail or f"Request failed with status {response.status_code}."