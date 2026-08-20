#!/usr/bin/env python3

import csv
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# CONFIGURATION

GAM_COMMAND = "/home/administrator/bin/gam7/gam"

# Persistent desired-state database.
# This file contains only users who should currently exist on
# the copiers.
DATABASE_FILE = Path("copier_users.csv")

# Temporary queue files.
# These should be processed by the copier provisioning script
# and deleted only after every copier completes successfully. (Current deletion occurs in copier_notify.py)
CREATE_QUEUE_FILE = Path("copier_create_queue.csv")
DELETE_QUEUE_FILE = Path("copier_delete_queue.csv")

# Location of copier_account_manager.py
ACCOUNT_MANAGER_SCRIPT = Path(
    __file__
).resolve().with_name(
    "copier_account_manager.py"
)

STAFF_OU = "/staff"
SERVICE_ACCOUNTS_OU = "/Service Accounts"

MIN_COPIER_CODE = 1000
MAX_COPIER_CODE = 1999


DATABASE_FIELDS = [
    "google_id",
    "primary_email",
    "first_name",
    "last_name",
    "display_name",
    "org_unit_path",
    "copier_code",
]


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


# GENERAL HELPERS

def normalize_ou(path):

    return (
        str(path or "")
        .strip()
        .rstrip("/")
        .casefold()
    )


def is_eligible_ou(org_unit_path):
    """
    Included:

        /staff
        All descendants of /staff
        All descendants of /Service Accounts

    Excluded:

        /Service Accounts itself
        All unrelated OUs
    """

    normalized = normalize_ou(
        org_unit_path
    )

    staff = normalize_ou(
        STAFF_OU
    )

    service_accounts = normalize_ou(
        SERVICE_ACCOUNTS_OU
    )

    if (
        normalized == staff
        or normalized.startswith(
            staff + "/"
        )
    ):
        return True

    if normalized.startswith(
        service_accounts + "/"
    ):
        return True

    return False


def first_present(row, *field_names):
    """
    Return the first non-empty matching field from a CSV row.

    This tolerates minor GAM CSV heading differences.
    """

    normalized_row = {
        str(key).strip().casefold(): value
        for key, value in row.items()
        if key is not None
    }

    for field_name in field_names:
        value = normalized_row.get(
            field_name.casefold()
        )

        if value is None:
            continue

        value = str(value).strip()

        if value:
            return value

    return ""


def clean_record(row, field_names):
    """
    Return a clean record containing exactly the requested fields.
    """

    return {
        field: str(
            row.get(field, "") or ""
        ).strip()
        for field in field_names
    }


def render_command(command):
    """
    Render a command list for readable error output.
    """

    rendered_parts = []

    for part in command:
        part = str(part)

        if (
            " " in part
            or "'" in part
            or '"' in part
        ):
            rendered_parts.append(
                repr(part)
            )
        else:
            rendered_parts.append(
                part
            )

    return " ".join(
        rendered_parts
    )


# GAM USER EXPORT

def run_gam_user_query(org_unit_path):
    """
    Query active, non-suspended users from a specific OU tree.

    Equivalent GAM command:

        gam print users query \
            "orgUnitPath='/staff' isSuspended=false" \
            fields "id,primaryemail,name,orgunitpath"
    """

    query = (
        f"orgUnitPath='{org_unit_path}' "
        f"isSuspended=false"
    )

    command = [
        GAM_COMMAND,
        "print",
        "users",
        "query",
        query,
        "fields",
        "id,primaryemail,name,orgunitpath",
    ]

    print(
        f"Loading active Google users from "
        f"{org_unit_path}..."
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

    except FileNotFoundError as error:
        raise RuntimeError(
            f"Could not find the GAM command "
            f"{GAM_COMMAND!r}. Update GAM_COMMAND "
            f"at the top of the script."
        ) from error

    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "GAM returned an unknown error."
        )

        raise RuntimeError(
            f"GAM failed while querying "
            f"{org_unit_path}:\n"
            f"Command: {render_command(command)}\n"
            f"{message}"
        )

    output = result.stdout.strip()

    if not output:
        return []

    reader = csv.DictReader(
        io.StringIO(output)
    )

    if reader.fieldnames is None:
        raise RuntimeError(
            "GAM did not return valid CSV output."
        )

    return list(reader)


def parse_gam_user(row):
    """
    Convert a GAM CSV row into the structure used by this script.
    """

    google_id = first_present(
        row,
        "id",
        "googleId",
    )

    primary_email = first_present(
        row,
        "primaryEmail",
        "email",
    ).casefold()

    first_name = first_present(
        row,
        "name.givenName",
        "givenName",
        "firstName",
    )

    last_name = first_present(
        row,
        "name.familyName",
        "familyName",
        "lastName",
    )

    display_name = first_present(
        row,
        "name.fullName",
        "fullName",
        "name",
    )

    org_unit_path = first_present(
        row,
        "orgUnitPath",
        "ou",
    )

    if not display_name:
        display_name = " ".join(
            part
            for part in (
                first_name,
                last_name,
            )
            if part
        ).strip()

    if not display_name:
        display_name = primary_email

    if not google_id:
        raise RuntimeError(
            "A GAM user record did not contain "
            f"a Google user ID:\n{row}"
        )

    if not primary_email:
        raise RuntimeError(
            "A GAM user record did not contain "
            f"a primary email address:\n{row}"
        )

    if not org_unit_path:
        raise RuntimeError(
            "A GAM user record did not contain "
            f"an organizational-unit path:\n{row}"
        )

    return {
        "google_id": google_id,
        "primary_email": primary_email,
        "first_name": first_name,
        "last_name": last_name,
        "display_name": display_name,
        "org_unit_path": org_unit_path,
    }


def get_eligible_google_users():
    """
    Retrieve the complete current set of eligible Google users.
    """

    raw_users = []

    raw_users.extend(
        run_gam_user_query(
            STAFF_OU
        )
    )

    raw_users.extend(
        run_gam_user_query(
            SERVICE_ACCOUNTS_OU
        )
    )

    # Deduplicate by immutable Google user ID.
    users_by_id = {}

    for raw_user in raw_users:
        user = parse_gam_user(
            raw_user
        )

        if not is_eligible_ou(
            user["org_unit_path"]
        ):
            continue

        users_by_id[
            user["google_id"]
        ] = user

    users = list(
        users_by_id.values()
    )

    # Stable assignment order for the first run.
    # This determines which user receives 1000, 1001, and so on
    # when no database exists yet.
    users.sort(
        key=lambda user: (
            user["display_name"].casefold(),
            user["primary_email"].casefold(),
            user["google_id"],
        )
    )

    return users


# DATABASE VALIDATION

def validate_database(records):
    """
    Validate the persistent current-state database.

    Every record must have:

        - A unique Google ID
        - A unique copier code
        - A numeric four-digit copier code
        - A code between 1000 and 2500
    """

    google_ids = set()
    copier_codes = {}

    for record in records:
        google_id = str(
            record.get(
                "google_id",
                "",
            )
        ).strip()

        primary_email = str(
            record.get(
                "primary_email",
                "",
            )
        ).strip()

        copier_code = str(
            record.get(
                "copier_code",
                "",
            )
        ).strip()

        if not google_id:
            raise RuntimeError(
                "A database record has a blank "
                "Google user ID."
            )

        if google_id in google_ids:
            raise RuntimeError(
                f"Duplicate Google user ID found: "
                f"{google_id}"
            )

        google_ids.add(
            google_id
        )

        if not primary_email:
            raise RuntimeError(
                f"Google user {google_id} has a "
                f"blank primary email address."
            )

        if not copier_code:
            raise RuntimeError(
                f"User {primary_email} does not have "
                f"a copier code."
            )

        if not copier_code.isdigit():
            raise RuntimeError(
                f"User {primary_email} has a "
                f"non-numeric copier code: "
                f"{copier_code!r}"
            )

        numeric_code = int(
            copier_code
        )

        if not (
            MIN_COPIER_CODE
            <= numeric_code
            <= MAX_COPIER_CODE
        ):
            raise RuntimeError(
                f"User {primary_email} has copier "
                f"code {copier_code}, which is outside "
                f"the permitted range "
                f"{MIN_COPIER_CODE}-"
                f"{MAX_COPIER_CODE}."
            )

        normalized_code = str(
            numeric_code
        )

        if len(normalized_code) != 4:
            raise RuntimeError(
                f"User {primary_email} has copier "
                f"code {copier_code}, which is not "
                f"exactly four digits."
            )

        existing_email = copier_codes.get(
            normalized_code
        )

        if existing_email is not None:
            raise RuntimeError(
                f"Users {existing_email} and "
                f"{primary_email} both have copier "
                f"code {normalized_code}."
            )

        copier_codes[
            normalized_code
        ] = primary_email

        # Normalize valid codes before rewriting the CSV.
        record["copier_code"] = (
            normalized_code
        )


# CSV READING AND WRITING

def load_database():
    """
    Load the persistent current-state copier user database.
    If the file does not exist, return an empty list.
    """

    if not DATABASE_FILE.exists():
        return []

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
                f"a valid CSV header."
            )

        missing_fields = [
            field
            for field in DATABASE_FIELDS
            if field not in reader.fieldnames
        ]

        if missing_fields:
            raise RuntimeError(
                f"{DATABASE_FILE} is missing required "
                f"columns: {', '.join(missing_fields)}"
            )

        records = []

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            record = clean_record(
                row,
                DATABASE_FIELDS,
            )

            if not any(
                record.values()
            ):
                continue

            if not record["google_id"]:
                raise RuntimeError(
                    f"{DATABASE_FILE} row "
                    f"{row_number} has a blank "
                    f"google_id."
                )

            records.append(
                record
            )

    validate_database(
        records
    )

    return records


def atomic_write_csv(
    destination,
    field_names,
    records,
):
    """
    Safely write a CSV to a temporary file and then replace the
    destination after the write completes.
    """

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f"{destination.stem}_",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_file = Path(
                file.name
            )

            writer = csv.DictWriter(
                file,
                fieldnames=field_names,
                extrasaction="ignore",
            )

            writer.writeheader()
            writer.writerows(
                records
            )

        os.replace(
            temporary_file,
            destination,
        )

    finally:
        if (
            temporary_file is not None
            and temporary_file.exists()
        ):
            temporary_file.unlink()


def write_database(records):
    """
    Validate and write the current-state database.
    The database is sorted numerically by copier code.
    """

    validate_database(
        records
    )

    sorted_records = sorted(
        records,
        key=lambda record: int(
            record["copier_code"]
        ),
    )

    atomic_write_csv(
        DATABASE_FILE,
        DATABASE_FIELDS,
        sorted_records,
    )


def write_creation_queue(records):
    """
    Write users who need to be created on the copiers.
    The queue is written even when it is empty. In that case, it
    contains only the CSV header.
    """

    sorted_records = sorted(
        records,
        key=lambda record: int(
            record["copier_code"]
        ),
    )

    atomic_write_csv(
        CREATE_QUEUE_FILE,
        CREATE_QUEUE_FIELDS,
        sorted_records,
    )


def write_deletion_queue(records):
    """
    Write users who need to be removed from the copiers.
    """

    queue_records = []

    for record in records:
        queue_records.append(
            {
                field: record.get(
                    field,
                    "",
                )
                for field in DELETE_QUEUE_FIELDS
            }
        )

    queue_records.sort(
        key=lambda record: int(
            record["copier_code"]
        )
    )

    atomic_write_csv(
        DELETE_QUEUE_FILE,
        DELETE_QUEUE_FIELDS,
        queue_records,
    )


# QUEUE SAFETY

def process_existing_queues():
    """
    If copier queue files from a previous run still exist,
    process them before performing a new reconciliation.

    copier_account_manager.py will process the outstanding
    copier work and copier_notify.py will remove the queues
    after everything completes successfully.

    If processing fails, an exception is raised and this
    reconciliation run stops. The existing queues remain
    available for the next retry.
    """

    create_exists = CREATE_QUEUE_FILE.exists()
    delete_exists = DELETE_QUEUE_FILE.exists()

    if not create_exists and not delete_exists:
        return

    print(
        "\nExisting copier queue files detected."
    )

    print(
        "Attempting to complete the previous "
        "copier batch before reconciliation..."
    )

    if create_exists:
        print(
            f"  - {CREATE_QUEUE_FILE.resolve()}"
        )

    if delete_exists:
        print(
            f"  - {DELETE_QUEUE_FILE.resolve()}"
        )

    # Both queue files should normally exist together.
    # copier_account_manager.py expects both files, so if
    # only one exists we stop rather than guessing what
    # happened to the other one.
    if create_exists != delete_exists:
        raise RuntimeError(
            "Only one copier queue file exists.\n"
            "Both the creation and deletion queues are "
            "required to safely resume processing.\n\n"
            "Manual intervention is required."
        )

    run_account_manager()

    # The account manager launches copier_notify.py, which
    # should remove both queues after successful completion.
    # Verify that actually happened before touching the
    # database or querying Google again.
    if (
        CREATE_QUEUE_FILE.exists()
        or DELETE_QUEUE_FILE.exists()
    ):
        raise RuntimeError(
            "The previous copier batch returned successfully, "
            "but one or more queue files still exist.\n"
            "Refusing to begin a new reconciliation."
        )

    print(
        "\nPrevious copier batch completed successfully."
    )

    print(
        "Continuing with current Google reconciliation..."
    )


# COPIER CODE ASSIGNMENT

def get_next_available_code(
    unavailable_codes,
):
    """
    Return the lowest available copier code.

    Codes are assigned sequentially:

        1000
        1001
        1002
        ...

    When a user is removed, their code becomes immediately
    available for reuse.
    """

    for number in range(
        MIN_COPIER_CODE,
        MAX_COPIER_CODE + 1,
    ):
        copier_code = str(
            number
        )

        if copier_code not in unavailable_codes:
            return copier_code

    raise RuntimeError(
        "No copier codes remain available in "
        f"the range {MIN_COPIER_CODE}-"
        f"{MAX_COPIER_CODE}."
    )


# RECONCILIATION

def update_existing_record(
    existing_record,
    google_user,
):
    """
    Refresh mutable Google information while preserving the
    user's current copier code.
    """

    existing_record[
        "primary_email"
    ] = google_user[
        "primary_email"
    ]

    existing_record[
        "first_name"
    ] = google_user[
        "first_name"
    ]

    existing_record[
        "last_name"
    ] = google_user[
        "last_name"
    ]

    existing_record[
        "display_name"
    ] = google_user[
        "display_name"
    ]

    existing_record[
        "org_unit_path"
    ] = google_user[
        "org_unit_path"
    ]


def build_new_record(
    google_user,
    copier_code,
):
    """
    Build a persistent record for a newly eligible user.
    """

    return {
        "google_id":
            google_user["google_id"],

        "primary_email":
            google_user["primary_email"],

        "first_name":
            google_user["first_name"],

        "last_name":
            google_user["last_name"],

        "display_name":
            google_user["display_name"],

        "org_unit_path":
            google_user["org_unit_path"],

        "copier_code":
            copier_code,
    }


def reconcile_users(
    google_users,
    existing_records,
):
    """
    Compare the current Google user set with the persistent CSV.

    Returns:

        records
            The complete new desired-state database.

        creations
            Users newly added during this reconciliation.

        deletions
            Previous users no longer eligible.

        continuing
            Existing users who remain eligible.

    Removed users are not retained in the new main database.
    """

    existing_by_id = {
        record["google_id"]: record
        for record in existing_records
    }

    google_by_id = {
        user["google_id"]: user
        for user in google_users
    }

    # Users in the old database but no longer in the eligible
    # Google user set must be deleted from the copiers.
    deletions = [
        record
        for google_id, record
        in existing_by_id.items()
        if google_id not in google_by_id
    ]

    # Only continuing users reserve codes.
    # Codes belonging to deleted users become available during
    # this same reconciliation run.
    unavailable_codes = {
        record["copier_code"]
        for google_id, record
        in existing_by_id.items()
        if google_id in google_by_id
    }

    final_records = []
    creations = []
    continuing = []

    for google_user in google_users:
        google_id = google_user[
            "google_id"
        ]

        existing_record = (
            existing_by_id.get(
                google_id
            )
        )

        # EXISTING USER

        if existing_record is not None:
            update_existing_record(
                existing_record,
                google_user,
            )

            final_records.append(
                existing_record
            )

            continuing.append(
                existing_record
            )

            continue

        # NEW USER

        copier_code = (
            get_next_available_code(
                unavailable_codes
            )
        )

        unavailable_codes.add(
            copier_code
        )

        new_record = build_new_record(
            google_user,
            copier_code,
        )

        final_records.append(
            new_record
        )

        creations.append(
            new_record
        )

    validate_database(
        final_records
    )

    return {
        "records": final_records,
        "creations": creations,
        "deletions": deletions,
        "continuing": continuing,
    }


# REPORTING

def print_user_group(
    title,
    records,
):
    """
    Print a readable list of users and copier codes.
    """

    if not records:
        return

    print(
        f"\n{title}:"
    )

    sorted_records = sorted(
        records,
        key=lambda record: int(
            record["copier_code"]
        ),
    )

    for record in sorted_records:
        print(
            f"  [{record['copier_code']}] "
            f"{record['display_name']} "
            f"<{record['primary_email']}>"
        )


def print_summary(result):
    """
    Print the reconciliation totals and output paths.
    """

    active_count = len(
        result["records"]
    )

    used_codes = {
        record["copier_code"]
        for record in result["records"]
    }

    total_capacity = (
        MAX_COPIER_CODE
        - MIN_COPIER_CODE
        + 1
    )

    available_count = (
        total_capacity
        - len(used_codes)
    )

    print(
        "\n"
        + "=" * 64
    )

    print(
        "COPIER USER RECONCILIATION COMPLETE"
    )

    print(
        "=" * 64
    )

    print(
        f"Current eligible users: "
        f"{active_count}"
    )

    print(
        f"Existing users retained: "
        f"{len(result['continuing'])}"
    )

    print(
        f"Users queued for creation: "
        f"{len(result['creations'])}"
    )

    print(
        f"Users queued for deletion: "
        f"{len(result['deletions'])}"
    )

    print(
        f"Available copier codes: "
        f"{available_count}"
    )

    print(
        f"\nCode range: "
        f"{MIN_COPIER_CODE}-"
        f"{MAX_COPIER_CODE}"
    )

    print(
        f"\nCurrent database:\n"
        f"  {DATABASE_FILE.resolve()}"
    )

    print(
        f"\nCreation queue:\n"
        f"  {CREATE_QUEUE_FILE.resolve()}"
    )

    print(
        f"\nDeletion queue:\n"
        f"  {DELETE_QUEUE_FILE.resolve()}"
    )

    print_user_group(
        "CREATE",
        result["creations"],
    )

    print_user_group(
        "DELETE",
        result["deletions"],
    )

def run_account_manager():
    """
    Launch the copier queue-processing script after reconciliation
    and queue creation complete.
    """

    if not ACCOUNT_MANAGER_SCRIPT.exists():
        raise RuntimeError(
            "Copier account manager script was not found:\n"
            f"  {ACCOUNT_MANAGER_SCRIPT}"
        )

    print(
        "\nLaunching copier account manager..."
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ACCOUNT_MANAGER_SCRIPT),
        ],
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "copier_account_manager.py failed with "
            f"exit code {result.returncode}.\n"
            "The queue files have been preserved so "
            "the operation can be retried."
        )

    print(
        "\nCopier account manager completed successfully."
    )

# MAIN

def main():
    """
    Run the complete Google-to-CSV reconciliation.
    """

    # Never overwrite queues that may contain unfinished work.
    process_existing_queues()

    google_users = (
        get_eligible_google_users()
    )

    print(
        f"\nFound {len(google_users)} "
        f"eligible active Google users."
    )

    existing_records = (
        load_database()
    )

    print(
        f"Loaded {len(existing_records)} "
        f"users from the current database."
    )

    result = reconcile_users(
        google_users,
        existing_records,
    )

    # The main database is the new desired state.
    write_database(
        result["records"]
    )

    # The queue files contain only this run's changes.
    write_creation_queue(
        result["creations"]
    )

    write_deletion_queue(
        result["deletions"]
    )

    print_summary(
        result
    )

    run_account_manager()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\nCancelled."
        )

        raise SystemExit(130)

    except Exception as error:
        print(
            f"\nERROR: {error}"
        )

        raise SystemExit(1)