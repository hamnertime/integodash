# **Integodash**

Created by David Hamner  
Integodash is a comprehensive, self-hosted operations dashboard for Managed Service Providers. It integrates data from Freshservice and Datto RMM into a single, secure web interface, providing at-a-glance insights into both ticket management and client billing.  
Built with a focus on security and automation, Integodash uses a fully encrypted local database for all sensitive data and credentials. A built-in background scheduler keeps the data fresh automatically, making it a powerful tool for improving operational efficiency.

## **Features**

* **Secure Credential Storage**: All API keys and sensitive data are stored in a fully-encrypted SQLCipher database file.  
* **Web-Based UI Unlock**: The master password for the database is entered through a secure login page. No environment variables or plain text tokens are needed for day-to-day operation.  
* **SSL Encryption**: All web traffic between your browser and the server is encrypted using a self-generated SSL certificate.  
* **Dark/Light Theme Toggle**: User-selectable interface theme.  
* **Automated Background Syncing**: A built-in scheduler automatically runs data sync jobs in the background after the first successful login.  
* **Configurable Scheduler**: Enable, disable, and change the schedule for each sync job directly from the web UI.  
* **Billing Overview Dashboard**: A high-level view of client billing metrics based on users, devices, and contract types.  
* **Client Detail View**: Click on any client to see a detailed breakdown of their users, assets, and recent billable hours.  
* **Rich Text Notes**: Add and edit client-specific notes using Markdown for better formatting, including headers, lists, and code blocks.

## **Prerequisites**

Before you begin, ensure you have the following installed:

* Python 3.x  
* pip (Python package installer)  
* Git (For cloning the repository)  
* Freshservice API Key  
* Datto RMM API Credentials (Endpoint, Public Key, and Secret Key)

## **Setup**

Follow these steps to get the project up and running.

### **1\. Clone the Repository**

git clone \[https://github.com/hamnertime/Integodash.git\](https://github.com/hamnertime/Integodash.git)  
cd Integodash

### **2\. Install Python Dependencies**

This project requires Flask, Requests, SQLCipher support, and other libraries. The sqlcipher3-wheels package provides pre-compiled binaries for a pain-free installation on Windows, macOS, and Linux.  
pip install Flask requests sqlcipher3-wheels cryptography APScheduler Markdown bleach

### **3\. Generate SSL Certificate**

This application uses SSL to encrypt all web traffic. Run the provided Python script to generate a self-signed certificate.  
python generate\_cert.py

This will create two files in your project directory: cert.pem and key.pem.

### **4\. Initialize the Encrypted Database**

The first time you set up the project, you must run the initialization script. This script will create the encrypted brainhair.db file and prompt you to enter a master password and all your API keys.  
The initialization script uses a config.json file for default settings. You can create a local file named **config.override.json** to customize these settings without modifying the original. If config.override.json exists, the script will use its values instead of config.json. This is the recommended way to manage your custom configurations and keep them out of version control.  
Run the initialization script:  
python init\_db.py

You will be asked for:

1. A **master password** for the database. **You must remember this password.**  
2. Your Freshservice API Key.  
3. Your Datto RMM API Endpoint, Public Key, and Secret Key.

These credentials will be stored securely inside the encrypted database.  
**Important**: If you ever need to reset the database or change your API keys, you must delete the brainhair.db file and run python init\_db.py again.

## **Project Structure**

Here is a breakdown of the Python files in this project and their functions:

* **main.py**: The main Flask application file. It contains all the web routes, handles user sessions, and serves the HTML templates.  
* **billing.py**: Contains all the core logic for calculating client bills. It fetches data from the database, applies overrides, and calculates totals for users, assets, tickets, and backups.  
* **database.py**: Manages the connection to the encrypted SQLCipher database. It includes helper functions for querying and writing data, as well as logging all database transactions for auditing purposes.  
* **init\_db.py**: A one-time setup script that creates the encrypted database, builds the schema, and prompts the user for their API keys. It can also be used to migrate data from an older version of the database.  
* **scheduler.py**: A simple script that is called by the background scheduler to run the data sync jobs as separate processes. It handles logging the output and status of each job back to the database.  
* **utils.py**: Contains a collection of helper functions used throughout the application, including custom Jinja2 template filters for formatting dates and text.  
* **generate\_cert.py**: A utility script to generate the self-signed SSL certificate (cert.pem) and private key (key.pem) required to run the web server over HTTPS.  
* **pull\_freshservice.py**: A data sync script that connects to the Freshservice API to pull in all company and user information and stores it in the local database.  
* **pull\_datto.py**: A data sync script that connects to the Datto RMM API to pull in all client site and device (asset) information.  
* **pull\_ticket\_details.py**: A data sync script that fetches all closed tickets from Freshservice and calculates the total time spent on each, which is then used for billing calculations.  
* **set\_account\_numbers.py**: A utility script that can be run to automatically assign a unique account number to any company in Freshservice that is missing one.  
* **push\_account\_nums\_to\_datto.py**: A utility script that matches clients between Freshservice and Datto RMM and pushes the Freshservice account number to a custom field in Datto RMM for cross-platform linking.

### **Routes**

The routes/ directory contains Flask blueprints that organize the application's URL routes and views into modular components.

* **routes/auth.py**: Handles user authentication, including logging in with the master password and selecting a user profile from the database.  
* **routes/clients.py**: Manages the routes for the main billing dashboard, client detail pages, and all associated actions like adding notes, attachments, and exporting data.  
* **routes/assets.py**: Contains the routes and logic for displaying the comprehensive list of all tracked assets.  
* **routes/contacts.py**: Manages the routes for viewing and managing all client contacts.  
* **routes/settings.py**: Provides routes for the application's settings, including managing billing plans, scheduler jobs, users, and custom links.  
* **routes/\_\_init\_\_.py**: This file is an empty placeholder that marks the routes directory as a Python package.

### **Debug Scripts**

The debug/ directory contains developer utility scripts.

* **debug\_datto\_client.py**: A command-line tool for developers to quickly fetch and view the raw JSON data for a specific client site from the Datto RMM API.  
* **debug\_datto\_device.py**: A command-line tool to fetch raw JSON data for a specific device from the Datto RMM API.  
* **debug\_freshservice\_client.py**: A command-line tool for developers to quickly fetch and view the raw JSON data for a specific client from the Freshservice API.  
* **dump\_settings.py**: A developer utility to export the default billing plans from the database into a Python-friendly format that can be used in config.json.  
* **dump\_widget\_settings.py**: A utility for exporting a user's widget layout settings to a JSON format for use in development or for backing up a specific layout.

## **Usage**

### **1\. Run the Application**

Start the entire application (web server and background scheduler) with a single command. No environment variables are required.  
python main.py

The application will be running on https://0.0.0.0:5002/.

### **2\. Access and Unlock the Web UI**

Open a web browser and navigate to **https://localhost:5002**.

* **Browser Warning**: Your browser will display a security warning (e.g., "Your connection is not private"). This is expected because we are using a self-signed certificate. You must click "Advanced" and then "Proceed to localhost (unsafe)" to continue.  
* **Login**: You will be greeted by a login page. Enter the master password you created during initialization. This single action will unlock the UI for your browser session and start the background scheduler.

### **3\. Manage the Scheduler**

Navigate to the **Settings & Sync** page to view the status of the automated jobs, see their last run logs, change their schedules, and trigger them to run immediately.  
**Note:** After saving changes to a job's interval or enabled status, you must restart the main.py application for the changes to take effect.

### **4\. Running as Systemd Services (Recommended for Production/Autostart)**

This project includes example systemd service files in the ./startup/ directory (or you can create them as described below). These files allow main.py to run as background services and start automatically on boot.  
**Assumptions for service files:**

* Your project is in /home/integotec/integodash.  
* You are using a user named integotec.  
* You are using python3 from the system path (adjust to use a virtualenv path if needed, e.g., /home/integotec/integodash/pyenv/bin/python3).

**Setup Steps:**

1. Prepare Service Files:  
   Ensure you have the following service files (e.g., in a ./startup/ directory within your project, or create them directly in /etc/systemd/system/):  
   * integodash.service (for main.py)  
     (Refer to previous conversation or generate them based on the templates provided if you don't have them.)  
2. **Copy Service Files to Systemd Directory:**  
   sudo cp ./startup/integodash.service /etc/systemd/system/

   *(Adjust the source path ./startup/ if your files are located elsewhere.)*  
3. Reload Systemd Manager Configuration:  
   This makes systemd aware of the new service files.  
   sudo systemctl daemon-reload

4. **Enable the Services (to start on boot):**  
   sudo systemctl enable integodash.service

5. **Start the Services Immediately:**  
   sudo systemctl start integodash.service

6. **Check the Status of the Services:**  
   sudo systemctl status integodash.service

   You can also view logs for each service:  
   sudo journalctl \-u integodash.service \-f

## **License**

This project is licensed under the GNU Affero General Public License v3.0.  
Copyright (C) 2025 David Hamner
