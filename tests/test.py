import httpx

LOGIN_API = "https://uis.ptithcm.edu.vn/"  # cần xác nhận URL thật

def login_direct(username: str, password: str) -> dict:
    with httpx.Client() as client:
        resp = client.post(LOGIN_API, json={
            "username": username,
            "password": password,
            # có thể cần thêm client_id, grant_type... tùy cơ chế thật
        })
        resp.raise_for_status()
        data = resp.json()
        # data thường chứa access_token
        return data


def fetch_schedule_direct(access_token: str, hoc_ky: str) -> dict:
    with httpx.Client() as client:
        resp = client.post(
            "https://uis.ptithcm.edu.vn/api/sch/w-locdstkbtuanusertheohocky",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "filter": {"hoc_ky": hoc_ky, "ten_hoc_ky": ""},
                "additional": {
                    "paging": {"limit": 100, "page": 1},
                    "ordering": [{"name": None, "order_type": None}],
                },
            },
        )
        resp.raise_for_status()
        return resp.json()