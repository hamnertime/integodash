document.addEventListener('DOMContentLoaded', function() {
    const widgetLibraryBtn = document.getElementById('widget-library-btn');
    const widgetLibraryModal = document.getElementById('widgetLibraryModal');
    const closeButton = widgetLibraryModal.querySelector('.close-button');
    const widgetLibraryList = document.getElementById('widget-library-list');

    const allWidgets = {
        'clients': [
            { id: 'clients-table-widget', title: 'Clients Table' },
            { id: 'export-all-widget', title: 'Export All Invoices' }
        ],
        'assets': [
            { id: 'assets-table-widget', title: 'Assets Table' }
        ],
        'contacts': [
            { id: 'contacts-table-widget', title: 'Contacts Table' }
        ],
        'client_details': [
            { id: 'billing-period-selector-widget', title: 'Billing Period Selector' },
            { id: 'client-details-widget', title: 'Client Details' },
            { id: 'locations-widget', title: 'Locations' },
            { id: 'client-features-widget', title: 'Client Features' },
            { id: 'contract-details-widget', title: 'Contract Details' },
            { id: 'billing-receipt-widget', title: 'Billing Receipt' },
            { id: 'notes-widget', title: 'Client Notes' },
            { id: 'attachments-widget', title: 'Client Attachments' },
            { id: 'ticket-breakdown-widget', title: 'Ticket Breakdown' },
            { id: 'tracked-assets-widget', title: 'Tracked Assets & Users' }
        ],
        'client_settings': [
            { id: 'client-details-widget', title: 'Client Details' },
            { id: 'contract-details-widget', title: 'Contract Details' },
            { id: 'billing-overrides-widget', title: 'Billing Rate Overrides' },
            { id: 'feature-overrides-widget', title: 'Feature Overrides' },
            { id: 'asset-overrides-widget', title: 'Asset Billing Overrides' },
            { id: 'user-overrides-widget', title: 'User Billing Overrides' },
            { id: 'add-manual-asset-widget', title: 'Add Manual Asset' },
            { id: 'add-manual-user-widget', title: 'Add Manual User' },
            { id: 'custom-line-items-widget', title: 'Custom Line Items' }
        ],
        'settings': [
            { id: 'import-export-widget', title: 'Import / Export Settings' },
            { id: 'scheduler-widget', title: 'Automated Sync Scheduler' },
            { id: 'users-auditing-widget', title: 'Application Users & Auditing' },
            { id: 'billing-plans-widget', title: 'Default Billing Plan Settings' },
            { id: 'custom-links-widget', title: 'Add Custom Links' },
            { id: 'feature-options-widget', title: 'Feature Options Management' }
        ]
    };

    function getPageName() {
        const bodyClasses = document.body.className.split(' ');
        for (const cls of bodyClasses) {
            if (cls.endsWith('-page')) {
                return cls.replace('-page', '');
            }
        }
        const path = window.location.pathname;
        if (path.startsWith('/client/')) {
            if (path.endsWith('/details')) {
                return 'client_details';
            }
            if (path.endsWith('/settings')) {
                return 'client_settings';
            }
        }
        const page = path.split('/').pop();
        return page || 'clients';
    }

    function populateWidgetLibrary() {
        const pageName = getPageName();
        const pageWidgets = allWidgets[pageName] || [];
        widgetLibraryList.innerHTML = '';

        pageWidgets.forEach(widget => {
            const button = document.createElement('button');
            button.className = 'button';
            button.textContent = `Add ${widget.title}`;
            button.onclick = () => {
                const grid = document.querySelector('.grid-stack').gridstack;
                const el = document.querySelector(`#${widget.id}`);
                if (el) {
                    grid.makeWidget(el);
                }
                widgetLibraryModal.style.display = 'none';
            };
            widgetLibraryList.appendChild(button);
        });
    }

    widgetLibraryBtn.onclick = () => {
        populateWidgetLibrary();
        widgetLibraryModal.style.display = 'block';
    };

    closeButton.onclick = () => {
        widgetLibraryModal.style.display = 'none';
    };

    window.onclick = (event) => {
        if (event.target === widgetLibraryModal) {
            widgetLibraryModal.style.display = 'none';
        }
    };

    document.querySelectorAll('.grid-stack-item').forEach(item => {
        const removeButton = document.createElement('button');
        removeButton.className = 'remove-widget-btn';
        removeButton.innerHTML = '&times;';
        removeButton.onclick = () => {
            const grid = document.querySelector('.grid-stack').gridstack;
            grid.removeWidget(item);
        };
        item.querySelector('.grid-stack-item-content').prepend(removeButton);
    });
});
