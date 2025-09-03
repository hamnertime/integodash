// static/js/table_resizer.js

function makeTableResizable(table) {
    if (!table) return;

    const colgroup = table.querySelector('colgroup');
    if (!colgroup) {
        console.error("Resizable table requires a <colgroup> element.");
        return;
    }

    const headers = table.querySelectorAll('th');
    const cols = colgroup.querySelectorAll('col');
    let minWidths = [];

    // Set initial widths to prevent overlap on load
    cols.forEach((col, index) => {
        const header = headers[index];
        if (!header) return;
        const style = window.getComputedStyle(header);
        const padding = parseInt(style.paddingLeft) + parseInt(style.paddingRight);
        let maxTextWidth = 0;

        // Use a temporary, unconstrained span to accurately measure the required width for the content
        const tempSpan = document.createElement("span");
        tempSpan.style.whiteSpace = "nowrap";
        document.body.appendChild(tempSpan);

        const headerText = header.querySelector('a') ? header.querySelector('a').textContent : header.textContent;
        tempSpan.textContent = headerText;
        maxTextWidth = Math.max(maxTextWidth, tempSpan.offsetWidth);

        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const cell = row.children[index];
            if (cell) {
                tempSpan.textContent = cell.textContent;
                maxTextWidth = Math.max(maxTextWidth, tempSpan.offsetWidth);
            }
        });

        document.body.removeChild(tempSpan);

        // Set the initial width with a small buffer
        const initialWidth = maxTextWidth + padding + 15; // Added a bit more buffer
        col.style.width = `${initialWidth}px`;
        minWidths[index] = initialWidth;
    });


    headers.forEach((header, index) => {
        if (index === headers.length - 1) return; // No resizer on the last column

        let resizer = header.querySelector('.resizer');
        if (resizer) resizer.remove();

        resizer = document.createElement('div');
        resizer.className = 'resizer';
        header.appendChild(resizer);

        let x = 0;
        let w = 0;

        const mouseDownHandler = function(e) {
            e.preventDefault();
            x = e.clientX;
            const col = cols[index];
            w = col.offsetWidth;

            document.addEventListener('mousemove', mouseMoveHandler);
            document.addEventListener('mouseup', mouseUpHandler);
            resizer.classList.add('resizing');
        };

        const mouseMoveHandler = function(e) {
            const dx = e.clientX - x;
            const newWidth = w + dx;
            const col = cols[index];

            if (newWidth > minWidths[index]) {
                col.style.width = `${newWidth}px`;
            }
        };

        const mouseUpHandler = function() {
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', mouseMoveHandler);
            document.removeEventListener('mouseup', mouseUpHandler);
        };

        resizer.addEventListener('mousedown', mouseDownHandler);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.resizable-table').forEach(makeTableResizable);
});

// Make the function globally available so it can be called on dynamically loaded content
window.makeTableResizable = makeTableResizable;
