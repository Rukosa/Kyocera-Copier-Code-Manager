#!/usr/bin/env python3

import csv
import subprocess
from pathlib import Path


# CONFIGURATION

GAM_COMMAND = "/home/administrator/bin/gam7/gam"

CREATE_QUEUE_FILE = Path(
    "copier_create_queue.csv"
)

DELETE_QUEUE_FILE = Path(
    "copier_delete_queue.csv"
)

TECHNOLOGY_GROUP_EMAIL = (
    "hisdtech@hillsboroisd.org"
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

# GENERAL HELPERS

def render_command(command):
    """
    Render a subprocess command for readable error output.
    """

    rendered_parts = []

    for part in command:
        part = str(part)

        if (
            " " in part
            or "\n" in part
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


def load_queue(
    path,
    required_fields,
):
    """
    Load and validate a queue CSV.

    A header-only queue returns an empty list.
    """

    if not path.exists():
        raise RuntimeError(
            "Required queue file does not exist:\n"
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

            if not record.get(
                "copier_code"
            ):
                raise RuntimeError(
                    f"{path} row {row_number} has "
                    "a blank copier_code."
                )

            if not record[
                "copier_code"
            ].isdigit():
                raise RuntimeError(
                    f"{path} row {row_number} has "
                    "an invalid copier_code: "
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


def run_gam_email(
    recipient,
    subject,
    message,
):
    """
    Send one plain-text email through GAM.
    """

    command = [
        GAM_COMMAND,
        "sendemail",
        "to",
        recipient,
        "subject",
        subject,
        "textmessage",
        message,
    ]

    print(
        f"\nSending email to {recipient}..."
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
            f"Could not find GAM at "
            f"{GAM_COMMAND!r}."
        ) from error

    if result.returncode != 0:
        output = (
            result.stderr.strip()
            or result.stdout.strip()
            or "GAM returned an unknown error."
        )

        raise RuntimeError(
            f"GAM failed to send email to "
            f"{recipient}.\n"
            f"Command: {render_command(command)}\n"
            f"{output}"
        )

    print(
        f"Email command completed for "
        f"{recipient}."
    )


def remove_queue_files():
    """
    Remove both queues after all notification work succeeds.
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


# EMAIL CONTENT

def build_user_subject(
    record,
):
    """
    Build the subject for a user's copier-code email.
    """

    return (
        "Your Copier Code"
    )


def build_user_message(
    record,
):
    """
    Build the plain-text message sent to a newly created user.
    """

    first_name = record[
        "first_name"
    ].strip()

    display_name = record[
        "display_name"
    ].strip()

    copier_code = record[
        "copier_code"
    ]

    greeting_name = (
        first_name
        or display_name
        or "there"
    )

    return (
        f"Hello {greeting_name},\n\n"
        "Your district copier account has been created.\n\n"
        f"Your copier code is: {copier_code}\n\n"
        "Use this code when prompted at a district copier.\n\n"
        "Please keep this code private. If you need changes "
        "made to your copier account, contact the Technology "
        "Department.\n\n"
        "Hillsboro ISD Technology Department"
    )


def build_technology_subject(
    creation_records,
):
    """
    Build the technology-group summary subject.
    """

    count = len(
        creation_records
    )

    noun = (
        "Account"
        if count == 1
        else "Accounts"
    )

    return (
        f"Copier Provisioning Complete: "
        f"{count} New {noun}"
    )


def build_technology_message(
    creation_records,
):
    """
    Build one summary containing every newly created copier code.
    """

    count = len(
        creation_records
    )

    lines = [
        "Copier account provisioning completed successfully.",
        "",
        f"New accounts created: {count}",
        "",
    ]

    for record in creation_records:
        lines.append(
            f"{record['copier_code']} - "
            f"{record['display_name']} - "
            f"{record['primary_email']}"
        )

    lines.extend(
        [
            "",
            "All listed accounts were processed on every "
            "configured copier.",
            "",
            "This message was generated automatically by "
            "the copier account management system.",
        ]
    )

    return "\n".join(
        lines
    )


# NOTIFICATION PROCESSING

def notify_created_users(
    creation_records,
):
    """
    Email each newly created user their assigned copier code.
    """

    for index, record in enumerate(
        creation_records,
        start=1,
    ):
        recipient = record[
            "primary_email"
        ]

        display_name = record[
            "display_name"
        ]

        copier_code = record[
            "copier_code"
        ]

        print(
            f"\nUser notification "
            f"{index}/{len(creation_records)}:"
        )

        print(
            f"  User: {display_name}"
        )

        print(
            f"  Email: {recipient}"
        )

        print(
            f"  Copier code: {copier_code}"
        )

        run_gam_email(
            recipient=recipient,
            subject=build_user_subject(
                record
            ),
            message=build_user_message(
                record
            ),
        )


def notify_technology_group(
    creation_records,
):
    """
    Send one final summary after every user notification succeeds.
    """

    run_gam_email(
        recipient=TECHNOLOGY_GROUP_EMAIL,
        subject=build_technology_subject(
            creation_records
        ),
        message=build_technology_message(
            creation_records
        ),
    )


# MAIN

def main():
    """
    Process copier-account notifications.

    Order:

        1. Load both queues.
        2. If no users were created, send no notifications.
        3. Email every newly created user.
        4. Email the technology group after all user emails succeed.
        5. Delete both queues after complete success.
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
        "COPIER NOTIFICATION PROCESSOR"
    )

    print(
        "=" * 64
    )

    print(
        f"Created users: "
        f"{len(creation_records)}"
    )

    print(
        f"Deleted users: "
        f"{len(deletion_records)}"
    )

    if not creation_records:
        print(
            "\nNo newly created users require "
            "notification."
        )

        print(
            "No emails will be sent."
        )

        remove_queue_files()

        return

    notify_created_users(
        creation_records
    )

    print(
        "\nAll user notifications completed."
    )

    notify_technology_group(
        creation_records
    )

    print(
        "\nTechnology group notification completed."
    )

    # Queue deletion occurs only after all individual messages
    # and the final technology summary complete successfully.
    remove_queue_files()

    print(
        "\n"
        + "=" * 64
    )

    print(
        "ALL COPIER NOTIFICATIONS COMPLETED SUCCESSFULLY"
    )

    print(
        "=" * 64
    )


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\nCancelled. Queue files were preserved."
        )

        raise SystemExit(130)

    except Exception as error:
        print(
            f"\nERROR: {error}"
        )

        print(
            "\nQueue files were preserved. Correct the "
            "problem and rerun copier_notify.py."
        )

        raise SystemExit(1)