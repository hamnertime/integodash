# Integodash

Created by David Hamner

Integodash is a comprehensive, self-hosted operations dashboard for Managed Service Providers. It integrates data from Freshservice and Datto RMM into a single, secure web interface, providing at-a-glance insights into both ticket management and client billing.

Built with a focus on security and automation, Integodash uses a fully encrypted local database for all sensitive data and credentials. A built-in background scheduler keeps the data fresh automatically, making it a powerful tool for improving operational efficiency.

## Features

- **Secure Credential Storage**: All API keys and sensitive data are stored in a fully-encrypted SQLCipher database file.
- **Web-Based UI Unlock**: The master password for the database is entered through a secure login page. No environment variables or plain text tokens are needed for day-to-day operation.
- **SSL Encryption**: All web traffic between your browser and the server is encrypted using a self-generated SSL certificate.
- **Automated Background Syncing**: A built-in scheduler automatically runs data sync jobs in the background after the first successful login.
- **Configurable Scheduler**: Enable, disable, and change the schedule for each sync job directly from the web UI.
- **Billing Overview Dashboard**: A high-level view of client billing metrics based on users, devices, and contract types.
- **Client Detail View**: Click on any client to see a detailed breakdown of their users, assets, and recent billable hours.
- **Rich Text Notes**: Add and edit client-specific notes using Markdown for better formatting, including headers, lists, and code blocks.

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.x
- pip (Python package installer)
- Git (For cloning the repository)
- Freshservice API Key
- Datto RMM API Credentials (Endpoint, Public Key, and Secret Key)

## Setup

Follow these steps to get the project up and running.

### 1. Clone the Repository

```bash
git clone https://github.com/hamnertime/Integodash.git
cd Integodash
```

### 2. Install Python Dependencies

This project requires Flask, Requests, SQLCipher support, and other libraries. The sqlcipher3-wheels package provides pre-compiled binaries for a pain-free installation on Windows, macOS, and Linux.

```bash
pip install Flask requests sqlcipher3-wheels cryptography APScheduler Markdown bleach
```

### 3. Generate SSL Certificate

This application uses SSL to encrypt all web traffic. Run the provided Python script to generate a self-signed certificate.

```bash
python generate_cert.py
```

This will create two files in your project directory: `cert.pem` and `key.pem`.

### 4. Initialize the Encrypted Database

The first time you set up the project, you must run the initialization script. This script will create the encrypted `brainhair.db` file and prompt you to enter a master password and all your API keys.

```bash
python init_db.py
```

You will be asked for:

1. A **master password** for the database. **You must remember this password.**
2. Your Freshservice API Key.
3. Your Datto RMM API Endpoint, Public Key, and Secret Key.

These credentials will be stored securely inside the encrypted database.

**Important**: If you ever need to reset the database or change your API keys, you must delete the `brainhair.db` file and run `python init_db.py` again.

## Usage

### 1. Run the Application

Start the entire application (web server and background scheduler) with a single command. No environment variables are required.

```bash
python main.py
```

The application will be running on `https://0.0.0.0:5002/`.

### 2. Access and Unlock the Web UI

Open a web browser and navigate to **https://localhost:5002**.

- **Browser Warning**: Your browser will display a security warning (e.g., "Your connection is not private"). This is expected because we are using a self-signed certificate. You must click "Advanced" and then "Proceed to localhost (unsafe)" to continue.
- **Login**: You will be greeted by a login page. Enter the master password you created during initialization. This single action will unlock the UI for your browser session and start the background scheduler.

### 3. Manage the Scheduler

Navigate to the **Settings & Sync** page to view the status of the automated jobs, see their last run logs, change their schedules, and trigger them to run immediately.

**Note:** After saving changes to a job's interval or enabled status, you must restart the `main.py` application for the changes to take effect.

### 4. Running as Systemd Services (Recommended for Production/Autostart)

This project includes example `systemd` service files in the `./startup/` directory (or you can create them as described below). These files allow `main.py` to run as background services and start automatically on boot.

**Assumptions for service files:**
* Your project is in `/home/integotec/integodash`.
* You are using a user named `integotec`.
* You are using `python3` from the system path (adjust to use a virtualenv path if needed, e.g., `/home/integotec/integodash/pyenv/bin/python3`).

**Setup Steps:**

1.  **Prepare Service Files:**
    Ensure you have the following service files (e.g., in a `./startup/` directory within your project, or create them directly in `/etc/systemd/system/`):
    * `integodash.service` (for `main.py`)
    *(Refer to previous conversation or generate them based on the templates provided if you don't have them.)*

2.  **Copy Service Files to Systemd Directory:**
    ```bash
    sudo cp ./startup/integodash.service /etc/systemd/system/
    ```
    *(Adjust the source path `./startup/` if your files are located elsewhere.)*

3.  **Reload Systemd Manager Configuration:**
    This makes `systemd` aware of the new service files.
    ```bash
    sudo systemctl daemon-reload
    ```

4.  **Enable the Services (to start on boot):**
    ```bash
    sudo systemctl enable integodash.service
    ```

5.  **Start the Services Immediately:**
    ```bash
    sudo systemctl start integodash.service
    ```

6.  **Check the Status of the Services:**
    ```bash
    sudo systemctl status integodash.service
    ```
    You can also view logs for each service:
    ```bash
    sudo journalctl -u integodash.service -f

## License

This project is licensed under the GNU Affero General Public License v3.0.

Copyright (C) 2025 David Hamner
