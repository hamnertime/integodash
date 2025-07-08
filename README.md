# Billing Dashboard

This project provides a secure, web-based dashboard for managing client billing information by integrating data from Freshservice and Datto RMM. It uses a locally encrypted SQLite database to securely store all synchronized data and API credentials, and all web traffic is encrypted with SSL.

## Features

- **Secure Credential Storage**: All API keys and sensitive data are stored in a fully-encrypted SQLCipher database file.
- **Web-Based UI Unlock**: The master password for the database is entered through a secure login page in the web UI, not stored in environment variables.
- **SSL Encryption**: All web traffic between your browser and the server is encrypted using a self-signed SSL certificate.
- **Freshservice Integration**: Pulls company, user, and ticket time-tracking data.
- **Datto RMM Integration**: Pulls site and device data.
- **ID Synchronization**: Assigns unique account numbers in Freshservice and pushes them to Datto RMM sites.
- **Billing Calculation**: Calculates estimated monthly billing based on configurable plans.
- **Web Dashboard**: A Flask-based web interface to view billing summaries, configure plans, and trigger data syncs.
- **Client Detail View**: Click on any client on the main dashboard to see a detailed breakdown of their users, assets, and recent billable hours.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.x**: The project is written in Python.
- **pip**: Python package installer.
- **Git**: For cloning the repository.
- **Freshservice API Key**: An API key from your Freshservice instance.
- **Datto RMM API Credentials**: API endpoint, public key, and secret key for your Datto RMM instance.

## Setup

Follow these steps to get the project up and running.

### 1. Clone the Repository

```bash
git clone https://github.com/ruapotato/billing_dash.git
cd billing_dash
```

### 2. Install Python Dependencies

This project requires Flask, Requests, and SQLCipher support. The sqlcipher3-wheels package provides pre-compiled binaries for a pain-free installation on Windows, macOS, and Linux. The cryptography package is used to generate the SSL certificate.

```bash
pip install Flask requests sqlcipher3-wheels cryptography
```

### 3. Generate SSL Certificate

This application uses SSL to encrypt all web traffic. Run the provided Python script to generate a self-signed certificate.

```bash
python generate_cert.py
```

This will create two files: `cert.pem` and `key.pem`.

### 4. Initialize the Encrypted Database

The first time you set up the project, you must run the initialization script. This script will create the encrypted `brainhair.db` file and prompt you to enter a master password and all your API keys.

```bash
python init_db.py
```

You will be asked for:

- A master password for the database. You must remember this password.
- Your Freshservice API Key.
- Your Datto RMM API Endpoint, Public Key, and Secret Key.

These credentials will be stored securely inside the encrypted database.

**Important**: If you ever need to reset the database or change your API keys, you must delete the `brainhair.db` file and run `python init_db.py` again.

## Usage

### 1. Run the Flask Application

Start the web server with the following command:

```bash
python main.py
```

The application will be running on `https://0.0.0.0:5002/`.

### 2. Access the Web UI

Open a web browser and navigate to `https://localhost:5002`.

- **Browser Warning**: Your browser will display a security warning (e.g., "Your connection is not private"). This is expected because we are using a self-signed certificate. Click "Advanced" and then "Proceed to localhost (unsafe)" to continue.
- **Login**: You will be greeted by a login page. Enter the master password you created during initialization to unlock the database.

### 3. Synchronize Data

From the Settings Page (`/settings`), you can trigger the synchronization scripts. It's recommended to run them in this order:

1. **Assign Missing IDs**: Runs `set_account_numbers.py`.
2. **Sync from Freshservice**: Runs `pull_freshservice.py`. This is the most intensive script as it now fetches ticket time entries.
3. **Push IDs to Datto**: Runs `push_account_nums_to_datto.py`.
4. **Sync from Datto RMM**: Runs `pull_datto.py`.
