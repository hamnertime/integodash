document.addEventListener('DOMContentLoaded', function() {
    const widgetLibraryBtn = document.getElementById('widget-library-btn');
    const widgetLibraryModal = document.getElementById('widgetLibraryModal');
    const closeButton = widgetLibraryModal.querySelector('.close-button');
    const widgetLibraryList = document.getElementById('widget-library-list');

    const allWidgets = [
        { id: 'clients-table-widget', title: 'Clients Table', default: {w: 12, h: 8} },
        { id: 'export-all-widget', title: 'Export All Invoices', default: {w: 4, h: 2} },
        { id: 'assets-table-widget', title: 'Assets Table', default: {w: 12, h: 8} },
        { id: 'contacts-table-widget', title: 'Contacts Table', default: {w: 12, h: 8} },
        { id: 'billing-period-selector-widget', title: 'Billing Period Selector', default: {w: 12, h: 1} },
        { id: 'client-details-widget', title: 'Client Details', default: {w: 6, h: 4} },
        { id: 'locations-widget', title: 'Locations', default: {w: 6, h: 2} },
        { id: 'locations-settings-widget', title: 'Locations Settings', default: {w: 12, h: 4} },
        { id: 'client-features-widget', title: 'Client Features', default: {w: 6, h: 3} },
        { id: 'contract-details-widget', title: 'Contract Details', default: {w: 6, h: 3} },
        { id: 'billing-receipt-widget', title: 'Billing Receipt', default: {w: 6, h: 5} },
        { id: 'notes-widget', title: 'Client Notes', default: {w: 6, h: 4} },
        { id: 'attachments-widget', title: 'Client Attachments', default: {w: 6, h: 4} },
        { id: 'ticket-breakdown-widget', title: 'Ticket Breakdown', default: {w: 12, h: 4} },
        { id: 'tracked-assets-widget', title: 'Tracked Assets & Users', default: {w: 12, h: 4} },
        { id: 'billing-overrides-widget', title: 'Billing Rate Overrides', default: {w: 12, h: 6} },
        { id: 'feature-overrides-widget', title: 'Feature Overrides', default: {w: 12, h: 5} },
        { id: 'asset-overrides-widget', title: 'Asset Billing Overrides', default: {w: 12, h: 6} },
        { id: 'user-overrides-widget', title: 'User Billing Overrides', default: {w: 12, h: 6} },
        { id: 'add-manual-asset-widget', title: 'Add Manual Asset', default: {w: 6, h: 3} },
        { id: 'add-manual-user-widget', title: 'Add Manual User', default: {w: 6, h: 3} },
        { id: 'custom-line-items-widget', title: 'Custom Line Items', default: {w: 12, h: 5} },
        { id: 'import-export-widget', title: 'Import / Export Settings', default: {w: 6, h: 3} },
        { id: 'scheduler-widget', title: 'Automated Sync Scheduler', default: {w: 6, h: 4} },
        { id: 'users-auditing-widget', title: 'Application Users & Auditing', default: {w: 12, h: 5} },
        { id: 'billing-plans-widget', title: 'Default Billing Plan Settings', default: {w: 12, h: 8} },
        { id: 'custom-links-widget', title: 'Add Custom Links', default: {w: 6, h: 4} },
        { id: 'feature-options-widget', title: 'Feature Options Management', default: {w: 6, h: 5} }
    ];

    const uniqueWidgets = allWidgets.filter((widget, index, self) =>
    index === self.findIndex((w) => w.id === widget.id)
    ).sort((a, b) => a.title.localeCompare(b.title));

    function populateWidgetLibrary() {
        widgetLibraryList.innerHTML = '';
        uniqueWidgets.forEach(widget => {
            const button = document.createElement('button');
            button.className = 'button';
            button.textContent = `Add ${widget.title}`;
            button.onclick = () => {
                const grid = window.grid;
                const el = document.querySelector(`.grid-stack-item[gs-id='${widget.id}']`);

                if (el) {
                    if (el.gridstackNode === undefined || el.gridstackNode.grid === null) {
                        grid.makeWidget(el);
                    } else {
                        el.classList.add('widget-highlight');
                        setTimeout(() => el.classList.remove('widget-highlight'), 1000);
                    }
                } else {
                    const newWidgetEl = document.createElement('div');
                    newWidgetEl.setAttribute('gs-id', widget.id);
                    newWidgetEl.setAttribute('gs-w', widget.default.w);
                    newWidgetEl.setAttribute('gs-h', widget.default.h);
                    newWidgetEl.innerHTML = `<div class="grid-stack-item-content"><h2>${widget.title}</h2><p>Content for this widget is not available on the current page.</p></div>`;
                    addRemoveButton(newWidgetEl);
                    grid.addWidget(newWidgetEl);
                }
                widgetLibraryModal.style.display = 'none';
            };
            widgetLibraryList.appendChild(button);
        });
    }

    function addRemoveButton(item) {
        const removeButton = document.createElement('button');
        removeButton.className = 'remove-widget-btn';
        removeButton.innerHTML = '&times;';
        removeButton.onclick = () => {
            const grid = window.grid;
            grid.removeWidget(item);
        };
        const content = item.querySelector('.grid-stack-item-content');
        if (content) {
            content.prepend(removeButton);
        }
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
        addRemoveButton(item);
    });
});
