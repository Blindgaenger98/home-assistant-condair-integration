import json
import logging
import time

import aiohttp

_LOGGER = logging.getLogger(__name__)


class CondairApi:
    """Updated Condair Cloud API client:
    - Auth (login, refresh)
    - get_devices(), get_latest_datapoints() now parse 'Area OnOff' and 'Humidity Reference'
    - invoke_action for on/off, set humidity
    - Logs JSON payloads for debugging
    """

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        base_url: str = "https://hlkc-api-management.azure-api.net",
    ):
        self._session = session
        self._base_url = base_url

        # Token management
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0

        # REFRESH FALLBACK: User info (private)
        self._username: str | None = None
        self._password: str | None = None
        # REFRESH FALLBACK END

    # ---------------------------
    # Basic session & request
    # ---------------------------
    async def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _get_auth_header(self) -> dict:
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    async def _get_request(self, endpoint: str) -> dict | list:
        session = await self._ensure_session()
        url = f"{self._base_url}/{endpoint}"
        _LOGGER.debug("GET %s", url)

        async with session.get(url, headers=self._get_auth_header()) as resp:
            resp.raise_for_status()

            ctype = resp.headers.get("Content-Type", "").lower()
            if "application/json" in ctype:
                return await resp.json()
            text_body = await resp.text()
            _LOGGER.debug(
                "Non-JSON GET response, returning empty dict. Body: %s", text_body
            )
            return {}

    async def _post_request(self, endpoint: str, data: dict) -> dict | list:
        session = await self._ensure_session()
        url = f"{self._base_url}/{endpoint}"

        # Log the JSON payload
        try:
            pretty_data = json.dumps(data, indent=2)
        except (TypeError, ValueError):
            pretty_data = str(data)

        _LOGGER.debug("POST %s\nSending JSON:\n%s", url, pretty_data)

        async with session.post(
            url, json=data, headers=self._get_auth_header()
        ) as resp:
            resp.raise_for_status()

            ctype = resp.headers.get("Content-Type", "").lower()
            if "application/json" in ctype:
                return await resp.json()
            text_body = await resp.text()
            _LOGGER.debug(
                "Non-JSON POST response, returning empty dict. Body: %s", text_body
            )
            return {}

    # ---------------------------
    # Auth
    # ---------------------------
    async def authenticate(self, username: str, password: str) -> bool:
        try:
            endpoint = "userapi/users/signin"
            payload = {"username": username, "password": password}
            resp = await self._post_request(endpoint, payload)

            if isinstance(resp, dict) and "error" in resp:
                _LOGGER.error(
                    "Login failed: %s - %s",
                    resp["error"],
                    resp.get("error_description", ""),
                )
                return False

            if (
                not isinstance(resp, dict)
                or "access_token" not in resp
                or "refresh_token" not in resp
            ):
                _LOGGER.error("Unexpected login response: %s", resp)
                return False

            self._access_token = resp["access_token"]
            self._refresh_token = resp["refresh_token"]

            # REFRESH FALLBACK: Store user info
            self._username = username
            self._password = password
            # REFRESH FALLBACK END

            expires_in_str = resp.get("expires_in", "3600")
            try:
                expires_in = int(expires_in_str)
            except ValueError:
                expires_in = 3600

            self._token_expires_at = time.time() + expires_in - 30
            _LOGGER.info("Authenticated! Expires in %s seconds.", expires_in)
            return True

        except aiohttp.ClientResponseError as e:
            _LOGGER.error("HTTP error authenticating: %s", e)
            return False
        except aiohttp.ClientError as e:
            _LOGGER.error("Network error authenticating: %s", e)
            return False

    async def refresh_access_token(self) -> bool:
        if not self._refresh_token:
            _LOGGER.error("No refresh token available.")
            return False

        try:
            endpoint = "userapi/users/refresh"
            payload = {"refresh_token": self._refresh_token}
            resp = await self._post_request(endpoint, payload)

            if isinstance(resp, dict) and "error" in resp:
                _LOGGER.error("Refresh token error: %s", resp)

                # REFRESH FALLBACK: Try to re-authenticate
                if self._username and self._password:
                    _LOGGER.warning("Trying to re-authenticate.")
                    return await self.authenticate(self._username, self._password)
                else:
                    _LOGGER.error("No username/password to re-authenticate.")
                # REFRESH FALLBACK END

                return False

            self._access_token = resp.get("access_token")
            self._refresh_token = resp.get("refresh_token")

            expires_in_str = resp.get("expires_in", "3600")
            try:
                expires_in = int(expires_in_str)
            except ValueError:
                expires_in = 3600

            self._token_expires_at = time.time() + expires_in - 30
            _LOGGER.info("Token refreshed. Expires in %s seconds.", expires_in)
            return True

        except aiohttp.ClientError as e:
            _LOGGER.error("Network error refreshing token: %s", e)
            return False

    async def maybe_refresh_token(self) -> bool:
        if not self._access_token:
            _LOGGER.warning("No access token; must authenticate first.")
            return False

        if time.time() >= self._token_expires_at:
            _LOGGER.debug("Token expired or expiring soon, refreshing.")
            return await self.refresh_access_token()

        return True

    # ---------------------------
    # Data fetching
    # ---------------------------
    async def get_devices(self) -> list[dict]:
        await self.maybe_refresh_token()
        endpoint = "api/condair/sensor-instances?pageSize=999"
        resp = await self._get_request(endpoint)
        if isinstance(resp, dict) and "data" in resp:
            return resp["data"]
        _LOGGER.warning("Unexpected get_devices response: %s", resp)
        return []

    async def get_parent_instances(self):
        """Fetch parent instances (households)."""
        endpoint = "/api/condair/sensor-instances?pageSize=999"
        response = await self._get_request(endpoint)
        parent_instances = {}

        # Parse and group by parent instance
        for device in response:
            parent_instance_number = device.get("parentSerialNumber")
            parent_instance_name = device.get("parentInstanceName")
            if parent_instance_number not in parent_instances:
                parent_instances[parent_instance_number] = {
                    "parentInstanceNumber": parent_instance_number,
                    "parentInstanceName": parent_instance_name,
                }

        return list(parent_instances.values())

    async def get_latest_datapoints(self, unique_id: str) -> dict:
        """GET /api/condair/sensor-instances/{unique_id}/latest-datapoint-values
        We'll parse:
          - "Humidity Average" => humidity_avg
          - "Temperature Average" => temperature_avg
          - "Humidity Reference" => target_humidity
          - "Area OnOff" => is_on: bool
        etc.
        """
        await self.maybe_refresh_token()
        endpoint = f"api/condair/sensor-instances/{unique_id}/latest-datapoint-values"
        raw_data = await self._get_request(endpoint)

        if not isinstance(raw_data, list):
            _LOGGER.warning(
                "Expected a list from latest-datapoint-values, got: %s", raw_data
            )
            return {}

        parsed = {}
        for dp in raw_data:
            name = dp.get("dataPointName", "")
            val_str = dp.get("value")
            numeric_val = None
            if val_str is not None:
                try:
                    numeric_val = float(val_str)
                except ValueError:
                    pass

            # Current humidity reading
            if name == "Humidity Average" and numeric_val is not None:
                parsed["humidity_avg"] = numeric_val

            # Temperature reading
            elif name == "Temperature Average" and numeric_val is not None:
                parsed["temperature_avg"] = numeric_val

            # The user wants the "desired humidity" as "Humidity Reference"
            elif name == "Humidity Reference" and numeric_val is not None:
                parsed["target_humidity"] = numeric_val  # we'll store as float or int

            # The user wants to see "Area OnOff" as a bool is_on
            elif name == "Area OnOff":
                # e.g. "1" => on, "0" => off. numeric_val might be 1.0 or 0.0
                parsed["is_on"] = bool(numeric_val == 1.0)

        return parsed

    # ---------------------------
    # Actions
    # ---------------------------
    async def get_actions(self, unique_id: str) -> list[dict]:
        await self.maybe_refresh_token()
        endpoint = f"api/condair/sensor-instances/{unique_id}/actions"
        resp = await self._get_request(endpoint)
        if isinstance(resp, list):
            return resp
        _LOGGER.warning("Expected list from get_actions, got: %s", resp)
        return []

    async def invoke_action(
        self, action_id: str, unique_id: str, variable_value: str
    ) -> bool:
        await self.maybe_refresh_token()
        endpoint = "api/condair/invoke-action"
        payload = {
            "actionId": action_id,
            "uniqueId": unique_id,
            "variables": [{"value": variable_value, "varName": "$value$"}],
        }
        try:
            resp = await self._post_request(endpoint, payload)
            if isinstance(resp, dict) and "error" in resp:
                _LOGGER.error("invoke_action returned error: %s", resp)
                return False
            return True
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error on invoke_action: %s", err)
            return False

    async def set_on_off(self, unique_id: str, turn_on: bool) -> bool:
        actions = await self.get_actions(unique_id)
        onoff_action = next((a for a in actions if a.get("name") == "Area OnOff"), None)
        if not onoff_action:
            _LOGGER.error("No 'Area OnOff' action found for %s", unique_id)
            return False

        return await self.invoke_action(
            onoff_action["id"], unique_id, "1" if turn_on else "0"
        )

    async def set_humidity_reference(self, unique_id: str, humidity: int) -> bool:
        actions = await self.get_actions(unique_id)
        hr_action = next(
            (a for a in actions if a.get("name") == "Humidity Reference"), None
        )
        if not hr_action:
            _LOGGER.error("No 'Humidity Reference' action for %s", unique_id)
            return False

        return await self.invoke_action(hr_action["id"], unique_id, str(humidity))

    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            _LOGGER.debug("Closed aiohttp session.")
