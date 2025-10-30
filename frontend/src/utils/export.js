const escapeCsvCell = (cell) => {
    if (cell === undefined || cell === null) {
        return '';
    }
    const str = String(cell);
    if (str.includes("\"") || str.includes(',') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`
    }
    return str;
};

export const exportDataToCsv = (filename, data) => {
    if (!data || data.length === 0) {
        console.warn("No data to export.");
        return;
    }

    const headers = Object.keys(data[0]);
    const csvRows = [headers.join(",")];
    
    for (const row of data) {
        const values = headers.map(header => escapeCsvCell(row[header]));
        csvRows.push(values.join(","));
    }

    const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", filename);
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
};