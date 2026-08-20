#!/usr/bin/env python3

import csv
import ipaddress
import math
import re
import subprocess
import sys
from pathlib import Path

from curl_cffi import requests

USERNAME = "Admin"
PASSWORD = "password"

REQUEST_TIMEOUT = 30

COPIER_IPS_FILE = Path(
    "copier_ips.csv"
)

CREATE_QUEUE_FILE = Path(
    "copier_create_queue.csv"
)

DELETE_QUEUE_FILE = Path(
    "copier_delete_queue.csv"
)

DATABASE_FILE = Path(
    "copier_users.csv"
)

CREATE_QUEUE_FIELDS = [
    "google_id",
    "primary_email",
    "first_name",
    "last_name",
    "display_name",
    "org_unit_path",
    "copier_code",
]


DELETE_QUEUE_FIELDS = [
    "google_id",
    "primary_email",
    "display_name",
    "copier_code",
]

NOTIFICATION_SCRIPT = Path(
    __file__
).resolve().with_name(
    "copier_notify.py"
)

class Kyocera:

    def __init__(
        self,
        host,
        username,
        password,
        timeout=REQUEST_TIMEOUT,
    ):

        self.base = f"https://{host}"

        self.username = username
        self.password = password
        self.timeout = timeout

        self.session = requests.Session(
            impersonate="firefox"
        )

        self.session.verify = False

        # Job Accounting token
        self.account_hidden = None

        # Address Book token
        self.address_hidden = None

        # One Touch token
        self.one_touch_hidden = None

        # Cached copier data
        self._accounts = None
        self.address_book = None

        # Browser already has this cookie before login
        self.session.cookies.set("rtl", "0")

    # HTTP HELPERS

    def _get(self, url, **kwargs):

        kwargs.setdefault(
            "timeout",
            self.timeout,
        )

        return self.session.get(
            url,
            **kwargs,
        )

    def _post(self, url, **kwargs):

        kwargs.setdefault(
            "timeout",
            self.timeout,
        )

        return self.session.post(
            url,
            **kwargs,
        )

    def dump(self, response):

        print("\n" + "=" * 60)
        print(
            response.request.method,
            response.url,
        )
        print(
            "Status:",
            response.status_code,
        )
        print("=" * 60)

    def _check_response(
        self,
        response,
        message,
    ):

        if response.status_code != 200:
            raise RuntimeError(
                f"{message}: "
                f"HTTP {response.status_code}"
            )

    def _extract_hidden_token(
        self,
        text,
        token_name,
    ):

        match = re.search(
            r"_pp\.hiddenvalue\s*=\s*'([^']+)'",
            text,
        )

        if not match:
            raise RuntimeError(
                f"{token_name} hidden token not found"
            )

        return match.group(1)

    # LOGIN

    def login(self):

        print("\nLogging in...")

        payload = {
            "failhtmfile":
                "/startwlm/Start_Wlm.htm",

            "okhtmfile":
                "/startwlm/Start_Wlm.htm",

            "func":
                "authLogin",

            "arg03_LoginType":
                "_mode_off",

            "arg04_LoginFrom":
                "_wlm_login",

            "hidden":
                "",

            "arg05_AccountId":
                "",

            "arg06_DomainName":
                "",

            "arg01_UserName":
                self.username,

            "arg02_Password":
                self.password,

            "Login":
                "Login",

            "language":
                f"{self.base}/wlmeng/index.htm",

            "hiddRefreshDevice":
                "../startwlm/Hme_DvcSts.htm",

            "hiddRefreshPanelUsed":
                "../startwlm/Hme_PnlUsg.htm",

            "hiddRefreshPaperid":
                "../startwlm/Hme_Paper.htm",

            "hiddRefreshTonerid":
                "../startwlm/Hme_StplPnch.htm",

            "hiddRefreshStapleid":
                "../startwlm/Hme_Toner.htm",

            "hiddnBackNavIndx":
                "1",

            "hiddDestHistoryID":
                "0",

            "hndHeight":
                "0",
        }

        response = self._post(
            f"{self.base}/startwlm/login.cgi",
            data=payload,
            headers={
                "Referer":
                    f"{self.base}/startwlm/login.cgi"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Login request failed",
        )

        if "ID1" not in self.session.cookies:
            raise RuntimeError(
                "Login failed"
            )

        print("\nLogin successful")

        return True

    # JOB ACCOUNTING PAGE AND TOKEN

    def open_add_account_page(self):

        print(
            "\nOpening Add Account page..."
        )

        response = self._get(
            f"{self.base}/mngset/jobset/"
            "MngSet_JobAcc_NewAcc.htm",
            params={
                "arg1": "0",
                "arg2": "0",
                "arg3": "",
                "arg4": "0",
                "arg5": "",
                "arg6": "",
                "arg7": "1",
                "arg8": "0",
                "arg9": "",
                "arg10": "",
                "arg11": "",
                "arg12": "0",
            },
            headers={
                "Referer":
                    f"{self.base}/startwlm/login.cgi"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Could not open Add Account page",
        )

        return response.text

    def fetch_hidden_token(self):

        """
        Fetch the Job Accounting hidden token.

        The method name is preserved from the original code.
        """

        print(
            "\nFetching Job Accounting hidden token..."
        )

        response = self._get(
            f"{self.base}/js/jssrc/model/"
            "mngset/jobset/"
            "MngSet_JobAcc_NewAcc.model.htm",
            params={
                "arg1": "0",
                "arg2": "0",
                "arg3": "",
                "arg4": "0",
                "arg5": "",
                "arg6": "",
                "arg7": "1",
                "arg8": "0",
                "arg9": "",
                "arg10": "",
                "arg11": "",
                "arg12": "0",
                "arg13": "",
            },
            headers={
                "Referer":
                    f"{self.base}/mngset/jobset/"
                    "MngSet_JobAcc_NewAcc.htm?"
                    "arg1=0&arg2=0&arg3=&arg4=0"
                    "&arg5=&arg6=&arg7=1&arg8=0"
                    "&arg9=&arg10=&arg11=&arg12=0"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Could not fetch Job Accounting model",
        )

        self.account_hidden = (
            self._extract_hidden_token(
                response.text,
                "Job Accounting",
            )
        )

        print(
            "\nJob Accounting hidden token fetched"
        )

        return self.account_hidden

    # JOB ACCOUNTING CREATION

    def create_account(
        self,
        name,
        code,
    ):

        if self.account_hidden is None:
            raise RuntimeError(
                "Job Accounting token has not been "
                "fetched. Call open_add_account_page() "
                "and fetch_hidden_token() first."
            )

        print(
            f"\nCreating account "
            f"{name} ({code})..."
        )

        payload = {
            "okhtmfile":
                "/mngset/jobset/"
                "MngSet_AddEditRslt.htm",

            "failhtmfile":
                "/mngset/jobset/MngSet_Err.htm",

            "func":
                "setJobAccAddEdit",

            "arg25_editType":
                "0",

            "arg26_deptId":
                "",

            "arg27":
                "0",

            "hidden":
                self.account_hidden,

            "arg01_Acname":
                name,

            "arg03_id":
                str(code),

            "arg04_copy":
                "0",

            "arg06_copycolor":
                "0",

            "arg08_copyfull":
                "0",

            "arg10_print":
                "0",

            "arg12_copy":
                "0",

            "arg20_scanother":
                "0",

            "submit001":
                "Submit",
        }

        response = self._post(
            f"{self.base}/mngset/jobset/set.cgi",
            data=payload,
            headers={
                "Referer":
                    f"{self.base}/mngset/jobset/"
                    "MngSet_JobAcc_NewAcc.htm?"
                    "arg1=0&arg2=0&arg3=&arg4=0"
                    "&arg5=&arg6=&arg7=1&arg8=0"
                    "&arg9=&arg10=&arg11=&arg12=0"
            },
        )

        self.dump(response)

        if (
            response.status_code == 200
            and "MngSet_AddEditRslt"
            in response.text
        ):
            print(
                "\nSUCCESS: Account created"
            )
            return True

        print(
            "\nWARNING: Unexpected response"
        )

        return False

    # JOB ACCOUNTING LISTING

    def _parse_accounts(
        self,
        text,
    ):

        pattern = re.compile(
            r"_pp\.sDeptPrivateID\[index\]\s*=\s*"
            r"'(?P<private>\d+)';.*?"
            r"_pp\.sDeptPublicID\[index\]\s*=\s*"
            r"'(?P<public>[^']+)';.*?"
            r"_pp\.sDeptName\[index\]\s*=\s*"
            r"'(?P<name>(?:\\.|[^'])*)';",
            re.S,
        )

        accounts = []

        for match in pattern.finditer(
            text
        ):
            name = match.group(
                "name"
            )

            name = (
                name
                .replace("\\'", "'")
                .replace("\\\\", "\\")
            )

            accounts.append(
                {
                    "private_id":
                        match.group("private"),

                    "code":
                        match.group("public"),

                    "name":
                        name,
                }
            )

        return accounts

    def get_account_page(
        self,
        page,
    ):

        response = self._get(
            f"{self.base}/js/jssrc/model/"
            "mngset/jobset/"
            "MngSet_JobAcc_JobAccLst.model.htm",
            params={
                "arg1": 1,
                "arg2": 0,
                "arg3": "",
                "arg4": 0,
                "arg5": "",
                "arg6": "",
                "arg7": page,
                "arg8": 0,
                "arg9": "",
                "arg10": "",
            },
            headers={
                "Referer":
                    f"{self.base}/mngset/jobset/"
                    "MngSet_JobAcc_JobAccLst.htm"
            },
        )

        self._check_response(
            response,
            f"Could not load account page {page}",
        )

        total_match = re.search(
            r"_pp\.TotsearchResult\s*=\s*'(\d+)'",
            response.text,
        )

        if not total_match:
            raise RuntimeError(
                f"Account total not found "
                f"on page {page}"
            )

        hidden_match = re.search(
            r"_pp\.hiddenvalue\s*=\s*'([^']+)'",
            response.text,
        )

        if hidden_match:
            self.account_hidden = (
                hidden_match.group(1)
            )

        return {
            "total":
                int(total_match.group(1)),

            "hidden":
                self.account_hidden,

            "accounts":
                self._parse_accounts(
                    response.text
                ),
        }

    def get_all_accounts(self):

        if self._accounts is not None:
            return self._accounts

        first = self.get_account_page(1)

        accounts = first["accounts"]
        total = first["total"]

        pages = math.ceil(total / 10)

        for page in range(
            2,
            pages + 1,
        ):

            print(
                f"Loading Job Accounting page "
                f"{page}/{pages}"
            )

            accounts.extend(
                self.get_account_page(
                    page
                )["accounts"]
            )

        self._accounts = accounts

        return self._accounts

    # JOB ACCOUNTING DELETION

    def delete_account(
        self,
        private_id,
    ):

        if self.account_hidden is None:
            raise RuntimeError(
                "Job Accounting token is unavailable. "
                "Call get_all_accounts() or "
                "fetch_hidden_token() first."
            )

        print(
            f"\nDeleting Job Accounting account "
            f"{private_id}..."
        )

        payload = {
            "okhtmfile":
                "/mngset/jobset/"
                "MngSet_Acc_DeleteRslt.htm",

            "failhtmfile":
                "/mngset/jobset/MngSet_Err.htm",

            "func":
                "setJobAcceDel",

            "arg01_Delmode":
                "0",

            "arg02_Num":
                "1",

            "arg03_ID":
                str(private_id),

            "hidden":
                self.account_hidden,
        }

        response = self._post(
            f"{self.base}/mngset/jobset/set.cgi",
            data=payload,
            headers={
                "Referer":
                    f"{self.base}/mngset/jobset/"
                    "MngSet_JobAcc_JobAccLst.htm"
            },
        )

        self.dump(response)

        if (
            response.status_code == 200
            and "MngSet_Acc_DeleteRslt"
            in response.text
        ):
            print(
                "\nSUCCESS: Account deleted"
            )
            return True

        print(
            "\nWARNING: Unexpected response"
        )

        return False

    def find_account(
        self,
        code=None,
        name=None,
    ):

        for account in self.get_all_accounts():

            if (
                code is not None
                and account["code"] == str(code)
            ):
                return account

            if (
                name is not None
                and account["name"] == name
            ):
                return account

        return None

    def delete_account_by_code(
        self,
        code,
    ):

        account = self.find_account(
            code=code
        )

        if account is None:
            raise RuntimeError(
                f"Job Accounting account "
                f"{code} not found."
            )

        return self.delete_account(
            account["private_id"]
        )

    def delete_account_by_name(
        self,
        name,
    ):

        account = self.find_account(
            name=name
        )

        if account is None:
            raise RuntimeError(
                f"Job Accounting account "
                f"'{name}' not found."
            )

        return self.delete_account(
            account["private_id"]
        )

    # ADDRESS BOOK PAGE AND TOKEN

    def open_add_address_page(self):

        print(
            "\nOpening Add Address Book "
            "Entry page..."
        )

        response = self._get(
            f"{self.base}/basic/"
            "AddrBook_Addr_NewCntct_Prpty.htm",
            params={
                "arg1": "1",
                "arg2": "0",
                "arg3": "",
                "arg4": "0",
                "arg5": "",
                "arg6": "1",
                "arg50": "0",
            },
            headers={
                "Referer":
                    f"{self.base}/basic/"
                    "AddrBook_Addr.htm?"
                    "arg1=1&arg2=0&arg3="
                    "&arg4=1&arg50=0"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Could not open Add Address "
            "Book Entry page",
        )

        return response.text

    def fetch_address_hidden_token(self):

        print(
            "\nFetching Address Book "
            "hidden token..."
        )

        response = self._get(
            f"{self.base}/js/jssrc/model/basic/"
            "AddrBook_Addr_NewCntct_Prpty"
            ".model.htm",
            params={
                "arg1": "1",
                "arg2": "0",
                "arg3": "",
                "arg4": "0",
                "arg5": "",
                "arg6": "1",
                "arg50": "0",
            },
            headers={
                "Referer":
                    f"{self.base}/basic/"
                    "AddrBook_Addr_NewCntct_Prpty.htm?"
                    "arg1=1&arg2=0&arg3=&arg4=0"
                    "&arg5=&arg6=1&arg50=0"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Could not fetch Address Book model",
        )

        self.address_hidden = (
            self._extract_hidden_token(
                response.text,
                "Address Book",
            )
        )

        print(
            "\nAddress Book hidden token fetched"
        )

        return self.address_hidden

    # ADDRESS BOOK LISTING

    def _parse_address_book(
        self,
        text,
    ):

        pattern = re.compile(
            r"_pp\.AddrNumber\[index\]\s*=\s*"
            r"'(?P<number>\d+)';.*?"
            r"_pp\.AddrType\[index\]\s*=\s*"
            r"'(?P<name>(?:\\.|[^'])*)';.*?"
            r"_pp\.publicPrivate\[index\]\s*=\s*"
            r"'(?P<private>\d+)';",
            re.S,
        )

        accounts = []

        for match in pattern.finditer(
            text
        ):
            name = match.group(
                "name"
            )

            # Decode escaped JavaScript apostrophes/backslashes.
            name = (
                name
                .replace("\\'", "'")
                .replace("\\\\", "\\")
                .replace("&nbsp;", " ")
            )

            accounts.append(
                {
                    "private_id":
                        match.group("private"),

                    "number":
                        match.group("number"),

                    "name":
                        name,
                }
            )

        return accounts

    def get_address_book_page(
        self,
        page,
        search="",
    ):

        response = self._get(
            f"{self.base}/js/jssrc/model/basic/"
            "AddrBook_Addr.model.htm",
            params={
                "arg1": str(page),
                "arg2": "0",
                "arg3": search,
                "arg4": "1",
                "arg5": "",
                "arg6": "",
                "arg7": "",
                "arg8": "0",
                "arg9": "",
                "arg50": "0",
            },
            headers={
                "Referer":
                    f"{self.base}/basic/"
                    "AddrBook_Addr.htm?"
                    f"arg1={page}"
                    "&arg2=0"
                    f"&arg3={search}"
                    "&arg4=1"
                    "&arg8=0"
                    "&arg50=0"
            },
        )

        self._check_response(
            response,
            f"Could not load Address Book "
            f"page {page}",
        )

        total_match = re.search(
            r"_pp\.TotsearchResult\s*=\s*'(\d+)'",
            response.text,
        )

        if not total_match:
            raise RuntimeError(
                f"Address Book total not found "
                f"on page {page}"
            )

        search_result_match = re.search(
            r"_pp\.searchResult\s*=\s*'(\d+)'",
            response.text,
        )

        hidden_match = re.search(
            r"_pp\.hiddenvalue\s*=\s*'([^']+)'",
            response.text,
        )

        if hidden_match:
            self.address_hidden = (
                hidden_match.group(1)
            )

        return {
            "total":
                int(total_match.group(1)),

            "search_total":
                (
                    int(
                        search_result_match.group(1)
                    )
                    if search_result_match
                    else 0
                ),

            "accounts":
                self._parse_address_book(
                    response.text
                ),

            "text":
                response.text,
        }

    def get_all_address_book(
        self,
        refresh=False,
    ):

        if (
            self.address_book is not None
            and not refresh
        ):
            return self.address_book

        first = self.get_address_book_page(1)

        accounts = list(
            first["accounts"]
        )

        total = first["total"]

        pages = math.ceil(total / 10)

        for page in range(
            2,
            pages + 1,
        ):

            print(
                f"Loading Address Book page "
                f"{page}/{pages}"
            )

            result = (
                self.get_address_book_page(
                    page
                )
            )

            accounts.extend(
                result["accounts"]
            )

        self.address_book = accounts

        print(
            f"\nLoaded {len(accounts)} "
            f"Address Book entries."
        )

        return self.address_book

    def find_address(
        self,
        number=None,
        name=None,
        refresh=False,
    ):

        accounts = (
            self.get_all_address_book(
                refresh=refresh
            )
        )

        normalized_number = None

        if number is not None:
            normalized_number = (
                str(number).lstrip("0")
                or "0"
            )

        for account in accounts:

            account_number = (
                str(
                    account["number"]
                ).lstrip("0")
                or "0"
            )

            if (
                normalized_number is not None
                and account_number
                == normalized_number
            ):
                return account

            if (
                name is not None
                and account["name"].replace(
                    "&nbsp;",
                    " ",
                ).strip().casefold()
                == str(name).strip().casefold()
            ):
                return account

        return None

    # ADDRESS BOOK CREATION

    def create_address(
        self,
        number,
        name,
        email,
    ):

        if self.address_hidden is None:
            raise RuntimeError(
                "Address Book token has not been "
                "fetched. Call "
                "open_add_address_page() and "
                "fetch_address_hidden_token() first."
            )

        print(
            f"\nCreating address book entry "
            f"{name} ({email})..."
        )

        payload = {
            "okhtmfile":
                "/basic/Contact_BasicRslt.htm",

            "failhtmfile":
                "/basic/Contact_BasicErr.htm",

            "func":
                "addAbpPersonal",

            "arg01_PageNum":
                "1",

            "arg02_Sort":
                "0",

            "arg03_Search":
                "",

            "arg04_pageType":
                "0",

            "arg05_MemoryID":
                "",

            "arg50":
                "0",

            "arg25_furi":
                "",

            "arg51":
                "0",

            "arg35":
                "1",

            "hidden":
                self.address_hidden,

            "arg06_sID":
                str(number).zfill(4),

            "arg07_Name":
                name,

            "arg08_Email":
                email,

            "arg09_SMBAddress":
                "",

            "arg38":
                "445",

            "arg10_SMBPathName":
                "",

            "arg11_SMBLoginName":
                "",

            "SMBPassword":
                "****************",

            "arg13_FTPAddress":
                "",

            "arg39":
                "21",

            "arg14_FTPPathName":
                "",

            "arg15_FTPLoginName":
                "",

            "FTPPassword":
                "****************",

            "arg17_FAXNumber":
                "",

            "submit001":
                "Submit",
        }

        response = self._post(
            f"{self.base}/basic/set.cgi",
            data=payload,
            headers={
                "Referer":
                    f"{self.base}/basic/"
                    "AddrBook_Addr_NewCntct_Prpty.htm?"
                    "arg1=1&arg2=0&arg3=&arg4=0"
                    "&arg5=&arg6=1&arg50=0",

                "Origin":
                    self.base,
            },
        )

        self.dump(response)

        if (
            response.status_code == 200
            and "Contact_BasicRslt"
            in response.text
        ):
            print(
                "\nSUCCESS: Address created"
            )
            return True

        print(
            "\nWARNING: Unexpected response"
        )

        return False

    # ADDRESS BOOK DELETION

    def delete_address(
        self,
        number,
        search="",
    ):

        if self.address_hidden is None:
            raise RuntimeError(
                "Address Book token is unavailable. "
                "Load the Address Book before deleting."
            )

        number = (
            str(number).lstrip("0")
            or "0"
        )

        print(
            f"\nDeleting Address Book number "
            f"{number}..."
        )

        payload = {
            "okhtmfile":
                "/basic/Contact_BasicDelRslt.htm",

            "failhtmfile":
                "/basic/Contact_BasicErr.htm",

            "func":
                "deleteAbpPersonalGroup",

            "arg01_PageNum":
                "1",

            "arg02_Sort":
                "0",

            "arg03_Search":
                search,

            "arg04_MemoryIDNum":
                "1",

            "arg05_AllID":
                "0",

            "arg06_MemoryID":
                "",

            "arg07_MemoryID":
                "",

            "arg08_MemoryID":
                "",

            "arg09_MemoryID":
                "",

            "arg10_MemoryID":
                "",

            "arg11_MemoryID":
                "",

            "arg12_MemoryID":
                "",

            "arg13_MemoryID":
                "",

            "arg14_MemoryID":
                "",

            "arg15_MemoryID":
                "",

            "arg16_ID":
                number,

            "arg17_Filtertype":
                "",

            "hidden":
                self.address_hidden,
        }

        print(
            "\nDeletion payload:"
        )

        for key, value in payload.items():

            if key == "hidden":
                value = "[REDACTED]"

            print(
                f"  {key}={value!r}"
            )

        response = self._post(
            f"{self.base}/basic/set.cgi",
            data=payload,
            headers={
                "Referer":
                    f"{self.base}/basic/"
                    "AddrBook_Addr.htm?"
                    "arg1=1"
                    "&arg2=0"
                    f"&arg3={search}"
                    "&arg4=1"
                    "&arg50=0",

                "Origin":
                    self.base,
            },
        )

        self.dump(response)

        if (
            response.status_code != 200
            or "Contact_BasicDelRslt"
            not in response.text
        ):
            print(
                "\nWARNING: Copier did not return "
                "the expected deletion result page."
            )
            return False

        self.address_book = None

        print(
            "\nDeletion request accepted by copier."
        )

        return True

    def delete_address_by_number(
        self,
        number,
    ):

        person = self.find_address(
            number=number,
            refresh=False,
        )

        if person is None:
            raise RuntimeError(
                f"Address Book entry "
                f"{number} not found."
            )

        return self.delete_address(
            person["number"]
        )

    def delete_address_by_name(
        self,
        name,
    ):

        person = self.find_address(
            name=name,
            refresh=False,
        )

        if person is None:
            raise RuntimeError(
                f"Address Book entry "
                f"'{name}' not found."
            )

        return self.delete_address(
            person["number"]
        )

    # ONE TOUCH KEYS

    def copier_code_to_one_touch_key(
        self,
        code,
    ):
        """
        Convert a managed copier code to its One Touch key.

        Examples:

            1001 -> 1
            1010 -> 10
            1262 -> 262
            1999 -> 999
            1000 -> 1000

        One Touch has only 1000 unique keys, so this mapping is
        unique only for copier codes 1000-1999.
        """

        code = int(code)

        if not 1000 <= code <= 1999:
            raise RuntimeError(
                f"Copier code {code} cannot be uniquely "
                "mapped to a One Touch key. "
                "One Touch-managed copier codes must currently "
                "be between 1000 and 1999."
            )

        key = code % 1000

        # There is no key 0. Code 1000 maps to key 1000.
        if key == 0:
            return 1000

        return key


    def open_one_touch_page(self):
        """
        Open the One Touch Key list page once to establish the
        browser-like navigation state.
        """

        print(
            "\nOpening One Touch Key page..."
        )

        response = self._get(
            f"{self.base}/adbk/otkset/"
            "Adbk_OtkSet_OtkSetLst.htm",
            params={
                "arg1": "1",
            },
            headers={
                "Referer":
                    f"{self.base}/startwlm/login.cgi"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Could not open One Touch Key page",
        )

        return response.text


    def fetch_one_touch_hidden_token(self):
        """
        Fetch the session token used for One Touch operations.

        The HAR shows the One Touch list model exposes the same
        hidden token for the session, so this only needs to be
        fetched once per copier session.
        """

        print(
            "\nFetching One Touch hidden token..."
        )

        response = self._get(
            f"{self.base}/js/jssrc/model/"
            "adbk/otkset/"
            "Adbk_OtkSet_OtkSetLst.model.htm",
            params={
                "arg1": "1",
                "arg3": "",
            },
            headers={
                "Referer":
                    f"{self.base}/adbk/otkset/"
                    "Adbk_OtkSet_OtkSetLst.htm?"
                    "arg1=1"
            },
        )

        self.dump(response)

        self._check_response(
            response,
            "Could not fetch One Touch model",
        )

        self.one_touch_hidden = (
            self._extract_hidden_token(
                response.text,
                "One Touch",
            )
        )

        print(
            "\nOne Touch hidden token fetched"
        )

        return self.one_touch_hidden


    def create_one_touch_key(
        self,
        key,
        address_private_id,
        name,
    ):
        """
        Create or set a One Touch email key.

        address_private_id is the copier-assigned internal
        Address Book reference.

        It is NOT the visible Address Book number.
        """

        if self.one_touch_hidden is None:
            raise RuntimeError(
                "One Touch token has not been fetched. "
                "Call open_one_touch_page() and "
                "fetch_one_touch_hidden_token() first."
            )

        print(
            f"\nCreating One Touch key {key} "
            f"for {name} "
            f"(internal Address ID "
            f"{address_private_id})..."
        )

        payload = {
            "okhtmfile":
                "/adbk/otkset/"
                "Adbk_ExtAbk_Rslt.htm",

            "failhtmfile":
                "/adbk/otkset/"
                "Adbk_ExtAbk_Err.htm",

            "func":
                "setOneTouchKeyProperty",

            "arg01":
                "1",

            # Actual One Touch key number
            "arg02":
                str(key),

            # Destination type 2 = email
            "arg04":
                "2",

            # Copier's INTERNAL Address Book reference
            "arg05":
                str(address_private_id),

            "tmpvalue":
                "",

            "hidden":
                self.one_touch_hidden,

            # Label displayed for the One Touch key
            "arg03_OneTouchName":
                name,

            "submit001":
                "Submit",
        }

        response = self._post(
            f"{self.base}/adbk/otkset/set.cgi",
            data=payload,
            headers={
                "Referer":
                    f"{self.base}/adbk/otkset/"
                    "Adbk_OtkSet_OtkSetPrty.htm",

                "Origin":
                    self.base,
            },
        )

        self.dump(response)

        if (
            response.status_code == 200
            and "Adbk_ExtAbk_Rslt"
            in response.text
        ):
            print(
                f"\nSUCCESS: One Touch key "
                f"{key} created"
            )

            return True

        print(
            f"\nWARNING: Unexpected One Touch "
            f"response for key {key}"
        )

        return False

    # SESSION CLEANUP

    def close(self):

        self.session.close()


# QUEUE-PROCESSING HELPERS

def load_queue(
    path,
    required_fields,
):
    """
    Load a queue CSV.

    A queue containing only its header returns an empty list.
    """

    if not path.exists():
        raise RuntimeError(
            f"Required queue file does not exist:\n"
            f"  {path.resolve()}"
        )

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(
            file
        )

        if reader.fieldnames is None:
            raise RuntimeError(
                f"{path} does not contain a valid "
                "CSV header."
            )

        missing_fields = [
            field
            for field in required_fields
            if field not in reader.fieldnames
        ]

        if missing_fields:
            raise RuntimeError(
                f"{path} is missing required columns: "
                f"{', '.join(missing_fields)}"
            )

        records = []

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            record = {
                field: str(
                    row.get(field, "") or ""
                ).strip()
                for field in required_fields
            }

            if not any(
                record.values()
            ):
                continue

            if not record["copier_code"]:
                raise RuntimeError(
                    f"{path} row {row_number} has a "
                    "blank copier_code."
                )

            if not record[
                "copier_code"
            ].isdigit():
                raise RuntimeError(
                    f"{path} row {row_number} has an "
                    "invalid copier_code: "
                    f"{record['copier_code']!r}"
                )

            records.append(
                record
            )

    records.sort(
        key=lambda record: int(
            record["copier_code"]
        )
    )

    return records


def load_copier_ips():
    """
    Load copier IP addresses from copier_ips.csv.

    The file contains one IP address per line and no header.
    Blank lines are ignored.
    """

    if not COPIER_IPS_FILE.exists():
        raise RuntimeError(
            "Copier IP file does not exist:\n"
            f"  {COPIER_IPS_FILE.resolve()}"
        )

    copier_ips = []
    seen_ips = set()

    with COPIER_IPS_FILE.open(
        "r",
        encoding="utf-8-sig",
    ) as file:
        for line_number, line in enumerate(
            file,
            start=1,
        ):
            host = line.strip()

            if not host:
                continue

            try:
                normalized_host = str(
                    ipaddress.ip_address(
                        host
                    )
                )

            except ValueError as error:
                raise RuntimeError(
                    f"{COPIER_IPS_FILE} line "
                    f"{line_number} contains an "
                    f"invalid IP address: {host!r}"
                ) from error

            if normalized_host in seen_ips:
                print(
                    f"WARNING: Ignoring duplicate "
                    f"copier IP {normalized_host}."
                )
                continue

            seen_ips.add(
                normalized_host
            )

            copier_ips.append(
                normalized_host
            )

    if not copier_ips:
        raise RuntimeError(
            f"{COPIER_IPS_FILE} does not contain "
            "any copier IP addresses."
        )

    return copier_ips


def remove_queue_files():
    """
    Delete both queue files after successful processing.
    """

    for path in (
        CREATE_QUEUE_FILE,
        DELETE_QUEUE_FILE,
    ):
        try:
            path.unlink()

        except FileNotFoundError:
            pass

    print(
        "\nQueue files removed successfully."
    )


def names_match(
    first_name,
    second_name,
):
    """
    Compare copier names without case or surrounding whitespace.
    """

    return (
        str(first_name).strip().casefold()
        == str(second_name).strip().casefold()
    )

# Database Loader for copier bootstrap

def load_bootstrap_database():
    """
    Load all current copier users from copier_users.csv.
    These records are used to populate a new or replacement
    copier without affecting the normal creation/deletion queues.
    """

    if not DATABASE_FILE.exists():
        raise RuntimeError(
            "Copier user database does not exist:\n"
            f"  {DATABASE_FILE.resolve()}"
        )

    with DATABASE_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(
            file
        )

        if reader.fieldnames is None:
            raise RuntimeError(
                f"{DATABASE_FILE} does not contain "
                "a valid CSV header."
            )

        missing_fields = [
            field
            for field in CREATE_QUEUE_FIELDS
            if field not in reader.fieldnames
        ]

        if missing_fields:
            raise RuntimeError(
                f"{DATABASE_FILE} is missing required columns: "
                f"{', '.join(missing_fields)}"
            )

        records = []

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            record = {
                field: str(
                    row.get(field, "") or ""
                ).strip()
                for field in CREATE_QUEUE_FIELDS
            }

            if not any(
                record.values()
            ):
                continue

            if not record["copier_code"]:
                raise RuntimeError(
                    f"{DATABASE_FILE} row "
                    f"{row_number} has a blank "
                    "copier_code."
                )

            if not record[
                "copier_code"
            ].isdigit():
                raise RuntimeError(
                    f"{DATABASE_FILE} row "
                    f"{row_number} has an invalid "
                    f"copier_code: "
                    f"{record['copier_code']!r}"
                )

            records.append(
                record
            )

    records.sort(
        key=lambda record: int(
            record["copier_code"]
        )
    )

    return records


# DELETION PROCESSING

def process_deletions_on_copier(
    host,
    deletion_records,
):
    """
    Process every deletion against one copier.

    Missing entries are treated as already completed, making
    retries safe.
    """

    print(
        "\n"
        + "=" * 64
    )

    print(
        f"DELETIONS ON COPIER {host}"
    )

    print(
        "=" * 64
    )

    copier = Kyocera(
        host,
        USERNAME,
        PASSWORD,
    )

    try:
        copier.login()

        # Load Job Accounting once.
        accounts = copier.get_all_accounts()

        # Load Address Book once.
        address_book = copier.get_all_address_book(
            refresh=True
        )

        # Build fast lookup tables from the snapshots.
        accounts_by_code = {
            str(account["code"]):
                account
            for account in accounts
        }

        addresses_by_number = {
            (
                str(
                    address["number"]
                ).lstrip("0")
                or "0"
            ):
                address
            for address in address_book
        }

        for record in deletion_records:
            copier_code = record[
                "copier_code"
            ]

            display_name = record[
                "display_name"
            ]

            normalized_code = (
                str(copier_code).lstrip("0")
                or "0"
            )

            print(
                f"\nDeleting {display_name} "
                f"[{copier_code}] from {host}..."
            )

            # JOB ACCOUNTING DELETION

            account = accounts_by_code.get(
                str(copier_code)
            )

            if account is None:
                print(
                    f"Job Accounting code "
                    f"{copier_code} is already absent."
                )

            else:
                success = copier.delete_account(
                    account["private_id"]
                )

                if not success:
                    raise RuntimeError(
                        f"Failed to delete Job Accounting "
                        f"code {copier_code} from {host}."
                    )

            # ADDRESS BOOK DELETION

            address = addresses_by_number.get(
                normalized_code
            )

            if address is None:
                print(
                    f"Address Book number "
                    f"{copier_code} is already absent."
                )

            else:
                success = copier.delete_address(
                    address["number"]
                )

                if not success:
                    raise RuntimeError(
                        f"Failed to delete Address Book "
                        f"number {copier_code} from "
                        f"{host}."
                    )

        print(
            f"\nAll deletions completed on {host}."
        )

    finally:
        copier.close()


# CREATION PROCESSING

def process_creations_on_copier(
    host,
    creation_records,
):
    """
    Process every creation against one copier.

    Processing occurs in two stages:

        Stage 1:
            Create Job Accounting and Address Book entries.

        Stage 2:
            Refresh the Address Book once, resolve each user's
            copier-assigned internal Address Book ID, and create
            their One Touch key.

    Existing matching entries are skipped.
    """

    print(
        "\n"
        + "=" * 64
    )

    print(
        f"CREATIONS ON COPIER {host}"
    )

    print(
        "=" * 64
    )

    copier = Kyocera(
        host,
        USERNAME,
        PASSWORD,
    )

    try:
        copier.login()

        # DOWNLOAD CURRENT STATE ONCE

        copier.get_all_accounts()

        copier.get_all_address_book(
            refresh=True
        )

        account_creation_ready = False
        address_creation_ready = False

        # =====================================================
        # STAGE 1
        # JOB ACCOUNTING + ADDRESS BOOK
        # =====================================================

        for record in creation_records:

            copier_code = record[
                "copier_code"
            ]

            display_name = record[
                "display_name"
            ]

            primary_email = record[
                "primary_email"
            ]

            print(
                f"\nCreating {display_name} "
                f"[{copier_code}] on {host}..."
            )

            # JOB ACCOUNTING

            existing_account = copier.find_account(
                code=copier_code
            )

            if existing_account is not None:

                if not names_match(
                    existing_account["name"],
                    display_name,
                ):
                    raise RuntimeError(
                        f"Job Accounting code "
                        f"{copier_code} already exists "
                        f"on {host} with the name "
                        f"{existing_account['name']!r}; "
                        f"expected {display_name!r}."
                    )

                print(
                    f"Job Accounting code "
                    f"{copier_code} already exists "
                    "correctly."
                )

            else:

                if not account_creation_ready:

                    copier.open_add_account_page()
                    copier.fetch_hidden_token()

                    account_creation_ready = True

                success = copier.create_account(
                    display_name,
                    copier_code,
                )

                if not success:
                    raise RuntimeError(
                        f"Failed to create Job "
                        f"Accounting code "
                        f"{copier_code} on {host}."
                    )

            # ADDRESS BOOK

            # Uses the cache downloaded once before this loop.
            existing_address = copier.find_address(
                number=copier_code
            )

            if existing_address is not None:

                if not names_match(
                    existing_address["name"],
                    display_name,
                ):
                    raise RuntimeError(
                        f"Address Book number "
                        f"{copier_code} already exists "
                        f"on {host} with the name "
                        f"{existing_address['name']!r}; "
                        f"expected {display_name!r}."
                    )

                print(
                    f"Address Book number "
                    f"{copier_code} already exists "
                    "with the expected name."
                )

            else:

                if not address_creation_ready:

                    copier.open_add_address_page()
                    copier.fetch_address_hidden_token()

                    address_creation_ready = True

                success = copier.create_address(
                    copier_code,
                    display_name,
                    primary_email,
                )

                if not success:
                    raise RuntimeError(
                        f"Failed to create Address "
                        f"Book number {copier_code} "
                        f"on {host}."
                    )

        # =====================================================
        # STAGE 2
        # ONE TOUCH KEYS
        # =====================================================

        if creation_records:

            print(
                "\n"
                + "-" * 64
            )

            print(
                "REFRESHING ADDRESS BOOK FOR "
                "ONE TOUCH REFERENCES"
            )

            print(
                "-" * 64
            )

            # This is the ONLY refresh after the creation loop.
            #
            # Newly created contacts now exist and their
            # copier-assigned internal IDs can be discovered.
            copier.get_all_address_book(
                refresh=True
            )

            # Fetch the One Touch token once for the entire
            # copier session.
            copier.open_one_touch_page()

            copier.fetch_one_touch_hidden_token()

            for record in creation_records:

                copier_code = record[
                    "copier_code"
                ]

                display_name = record[
                    "display_name"
                ]

                # CALCULATE ONE TOUCH KEY

                one_touch_key = (
                    copier.copier_code_to_one_touch_key(
                        copier_code
                    )
                )

                # LOOK UP ACTUAL INTERNAL ADDRESS BOOK ID

                address = copier.find_address(
                    number=copier_code
                )

                if address is None:
                    raise RuntimeError(
                        f"Cannot create One Touch key "
                        f"{one_touch_key} for "
                        f"{display_name} on {host}: "
                        f"Address Book number "
                        f"{copier_code} could not "
                        "be found after creation."
                    )

                address_private_id = address[
                    "private_id"
                ]

                print(
                    f"\nOne Touch mapping:"
                    f"\n  User: {display_name}"
                    f"\n  Copier code: {copier_code}"
                    f"\n  One Touch key: {one_touch_key}"
                    f"\n  Address Book number: "
                    f"{address['number']}"
                    f"\n  Internal Address ID: "
                    f"{address_private_id}"
                )

                success = (
                    copier.create_one_touch_key(
                        key=one_touch_key,
                        address_private_id=
                            address_private_id,
                        name=display_name,
                    )
                )

                if not success:
                    raise RuntimeError(
                        f"Failed to create One Touch "
                        f"key {one_touch_key} for "
                        f"{display_name} on {host}."
                    )

        print(
            f"\nAll creations completed on {host}."
        )

    finally:
        copier.close()

def run_notification_script():
    """
    Run copier_notify.py after all copier operations complete.

    The notification script is responsible for deleting the queue
    files after all required emails have been sent successfully.
    """

    if not NOTIFICATION_SCRIPT.exists():
        raise RuntimeError(
            "Notification script was not found:\n"
            f"  {NOTIFICATION_SCRIPT}"
        )

    print(
        "\nLaunching copier notification script..."
    )

    result = subprocess.run(
        [
            sys.executable,
            str(NOTIFICATION_SCRIPT),
        ],
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "copier_notify.py failed with exit code "
            f"{result.returncode}.\n"
            "The queue files have been preserved."
        )

    print(
        "\nCopier notification script completed successfully."
    )

# Copier bootstrap for new copiers

def bootstrap_copier(
    host,
):
    """
    Populate one copier with every user currently stored in
    copier_users.csv.
    Bootstrap mode:
        - Does not use the normal queue files.
        - Does not process deletions.
        - Does not notify users.
        - Does not modify copier_users.csv.
        - Only targets the supplied copier IP.
        - Existing matching entries are skipped.
    """

    try:
        host = str(
            ipaddress.ip_address(
                host
            )
        )

    except ValueError as error:
        raise RuntimeError(
            f"Invalid copier IP address: {host!r}"
        ) from error

    records = load_bootstrap_database()

    if not records:
        raise RuntimeError(
            f"{DATABASE_FILE} contains no users "
            "to bootstrap."
        )

    print(
        "\n"
        + "=" * 64
    )

    print(
        "COPIER BOOTSTRAP"
    )

    print(
        "=" * 64
    )

    print(
        f"Target copier: {host}"
    )

    print(
        f"Accounts to check/create: "
        f"{len(records)}"
    )

    print(
        "\nBootstrap does not modify the normal "
        "creation or deletion queues."
    )

    print(
        "No user notifications will be sent."
    )

    process_creations_on_copier(
        host,
        records,
    )

    print(
        "\n"
        + "=" * 64
    )

    print(
        f"BOOTSTRAP COMPLETED SUCCESSFULLY FOR {host}"
    )

    print(
        "=" * 64
    )

def create_all_one_touch_keys_on_copier(
    host,
    records,
):
    """
    Create One Touch keys for every current database user on one
    existing copier.

    This does NOT:
        - Create Job Accounting accounts
        - Create Address Book entries
        - Delete anything
        - Touch queue files
        - Send notifications

    It assumes the Address Book entries already exist.
    """

    print(
        "\n"
        + "=" * 64
    )

    print(
        f"ONE TOUCH SYNC ON COPIER {host}"
    )

    print(
        "=" * 64
    )

    copier = Kyocera(
        host,
        USERNAME,
        PASSWORD,
    )

    try:
        copier.login()

        # LOAD ADDRESS BOOK ONCE

        print(
            "\nLoading Address Book..."
        )

        copier.get_all_address_book(
            refresh=True
        )

        # PREPARE ONE TOUCH ONCE

        copier.open_one_touch_page()

        copier.fetch_one_touch_hidden_token()

        # CREATE KEYS

        for index, record in enumerate(
            records,
            start=1,
        ):

            copier_code = record[
                "copier_code"
            ]

            display_name = record[
                "display_name"
            ]

            one_touch_key = (
                copier.copier_code_to_one_touch_key(
                    copier_code
                )
            )

            # Find the user's actual Address Book entry.
            #
            # This uses the cached Address Book loaded above.
            address = copier.find_address(
                number=copier_code
            )

            if address is None:
                raise RuntimeError(
                    f"Cannot create One Touch key "
                    f"{one_touch_key} for "
                    f"{display_name} on {host}: "
                    f"Address Book entry "
                    f"{copier_code} was not found."
                )

            # IMPORTANT:
            #
            # private_id is the copier's internal sequential
            # reference and may be completely different from
            # copier_code.
            address_private_id = address[
                "private_id"
            ]

            print(
                f"\n[{index}/{len(records)}] "
                f"{display_name}"
            )

            print(
                f"  Copier code:        "
                f"{copier_code}"
            )

            print(
                f"  One Touch key:      "
                f"{one_touch_key}"
            )

            print(
                f"  Address Book slot:  "
                f"{address['number']}"
            )

            print(
                f"  Internal reference: "
                f"{address_private_id}"
            )

            success = (
                copier.create_one_touch_key(
                    key=one_touch_key,
                    address_private_id=
                        address_private_id,
                    name=display_name,
                )
            )

            if not success:
                raise RuntimeError(
                    f"Failed to create One Touch "
                    f"key {one_touch_key} for "
                    f"{display_name} on {host}."
                )

        print(
            f"\nAll One Touch keys completed "
            f"on {host}."
        )

    finally:
        copier.close()

def create_all_one_touch_keys():
    """
    One-time fleet migration.

    Create One Touch keys for every current copier user on every
    copier listed in copier_ips.csv.
    """

    records = load_bootstrap_database()

    if not records:
        raise RuntimeError(
            f"{DATABASE_FILE} contains no users."
        )

    copier_ips = load_copier_ips()

    print(
        "\n"
        + "#" * 64
    )

    print(
        "ONE TOUCH FLEET MIGRATION"
    )

    print(
        "#" * 64
    )

    print(
        f"Users:   {len(records)}"
    )

    print(
        f"Copiers: {len(copier_ips)}"
    )

    print(
        "\nThis operation only creates One Touch keys."
    )

    print(
        "Job Accounting, Address Book entries, "
        "queues, and notifications are untouched."
    )

    for host in copier_ips:
        create_all_one_touch_keys_on_copier(
            host,
            records,
        )

    print(
        "\n"
        + "=" * 64
    )

    print(
        "ONE TOUCH FLEET MIGRATION COMPLETE"
    )

    print(
        "=" * 64
    )

# MAIN QUEUE PROCESSOR

def main():
    """
    Process copier deletion and creation queues.

    Processing order:

        1. Read and validate both queues.
        2. Exit without connecting if both queues are empty.
        3. Process every deletion on every copier.
        4. Process every creation on every copier.
        5. Launch notification processor.
    """

    creation_records = load_queue(
        CREATE_QUEUE_FILE,
        CREATE_QUEUE_FIELDS,
    )

    deletion_records = load_queue(
        DELETE_QUEUE_FILE,
        DELETE_QUEUE_FIELDS,
    )

    print(
        "\n"
        + "=" * 64
    )

    print(
        "COPIER QUEUE PROCESSOR"
    )

    print(
        "=" * 64
    )

    print(
        f"Users queued for creation: "
        f"{len(creation_records)}"
    )

    print(
        f"Users queued for deletion: "
        f"{len(deletion_records)}"
    )

    # Empty queues still need to be removed. Otherwise,
    # copier_gam.py would refuse to run again.
    if (
        not creation_records
        and not deletion_records
    ):
        print(
            "\nNo copier changes are required."
        )

        print(
            "No copier connections will be made."
        )

        remove_queue_files()

        return

    copier_ips = load_copier_ips()

    print(
        f"\nLoaded {len(copier_ips)} copier "
        "IP addresses."
    )

    # PHASE 1: ALL DELETIONS ON ALL COPIERS

    if deletion_records:
        print(
            "\n"
            + "#" * 64
        )

        print(
            "PHASE 1: DELETIONS"
        )

        print(
            "#" * 64
        )

        for host in copier_ips:
            process_deletions_on_copier(
                host,
                deletion_records,
            )

    else:
        print(
            "\nDeletion queue is empty. "
            "Skipping deletion phase."
        )

    # PHASE 2: ALL CREATIONS ON ALL COPIERS

    if creation_records:
        print(
            "\n"
            + "#" * 64
        )

        print(
            "PHASE 2: CREATIONS"
        )

        print(
            "#" * 64
        )

        for host in copier_ips:
            process_creations_on_copier(
                host,
                creation_records,
            )

    else:
        print(
            "\nCreation queue is empty. "
            "Skipping creation phase."
        )

    # This point is reached only if every requested operation
    # completed successfully on every copier.

    print(
        "\n"
        + "=" * 64
    )

    print(
        "ALL COPIERS COMPLETED SUCCESSFULLY"
    )

    print(
        "=" * 64
    )

    run_notification_script()


if __name__ == "__main__":

    bootstrap_mode = (
        len(sys.argv) >= 2
        and sys.argv[1] == "--bootstrap"
    )

    one_touch_all_mode = (
        len(sys.argv) >= 2
        and sys.argv[1] == "--onetouch-all"
    )

    try:

        # BOOTSTRAP ONE COPIER

        if bootstrap_mode:

            if len(sys.argv) != 3:
                raise RuntimeError(
                    "Bootstrap usage:\n"
                    "  python copier_account_manager.py "
                    "--bootstrap <copier_ip>"
                )

            bootstrap_copier(
                sys.argv[2]
            )

        # ONE-TIME ONE TOUCH MIGRATION

        elif one_touch_all_mode:

            if len(sys.argv) != 2:
                raise RuntimeError(
                    "One Touch migration usage:\n"
                    "  python copier_account_manager.py "
                    "--onetouch-all"
                )

            create_all_one_touch_keys()

        # NORMAL QUEUE PROCESSING

        else:

            if len(sys.argv) != 1:
                raise RuntimeError(
                    "Unknown command-line arguments.\n\n"

                    "Normal usage:\n"
                    "  python copier_account_manager.py\n\n"

                    "Bootstrap usage:\n"
                    "  python copier_account_manager.py "
                    "--bootstrap <copier_ip>\n\n"

                    "One Touch fleet migration:\n"
                    "  python copier_account_manager.py "
                    "--onetouch-all"
                )

            main()

    except KeyboardInterrupt:

        print(
            "\nCancelled."
        )

        if (
            not bootstrap_mode
            and not one_touch_all_mode
        ):
            print(
                "Queue files were preserved."
            )

        raise SystemExit(130)

    except Exception as error:

        print(
            f"\nERROR: {error}"
        )

        if bootstrap_mode:

            print(
                "\nBootstrap stopped. "
                "The normal copier queues and database "
                "were not modified."
            )

        elif one_touch_all_mode:

            print(
                "\nOne Touch migration stopped. "
                "The normal copier queues and database "
                "were not modified."
            )

        else:

            print(
                "\nQueue files were preserved. "
                "Correct the problem and rerun "
                "copier_account_manager.py."
            )

        raise SystemExit(1)