// Global variables
let currentPage = 1;
let pageSize = 50;
let currentTickets = [];
let filterOptions = {};
let selectedClient = '';
let selectedServices = [];
let allClients = [];
let clientServices = {};
let currentTimePeriod = 30; // Default to 30 days

// Timezone helper functions
function dateToUTC(dateString) {
    // Convierte una fecha local del usuario a UTC para enviar al servidor
    if (!dateString) return null;
    const localDate = new Date(dateString);
    return localDate.toISOString().split('T')[0]; // Formato YYYY-MM-DD en UTC
}

function formatDateTimeLocal(utcDateString) {
    // Convierte una fecha UTC del servidor a la hora local del usuario para mostrar
    if (!utcDateString) return '-';
    const utcDate = new Date(utcDateString);
    return utcDate.toLocaleString(); // Formato local del navegador
}

function formatDateLocal(utcDateString) {
    // Convierte una fecha UTC del servidor a solo la fecha local del usuario
    if (!utcDateString) return '-';
    const utcDate = new Date(utcDateString);
    return utcDate.toLocaleDateString(); // Solo fecha en formato local
}

// Color scheme for charts
const chartColors = {
    primary: '#2563EB',
    secondary: '#10B981',
    accent: '#F59E0B',
    danger: '#EF4444',
    info: '#3B82F6',
    muted: '#64748B'
};

// Chart.js default configuration
Chart.defaults.font.family = 'Inter';
Chart.defaults.font.size = 12;
Chart.defaults.color = '#1E293B';

// Utility functions
function showLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.classList.add('loading');
    }
}

function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.classList.remove('loading');
    }
}

function showError(message, containerId = null) {
    const errorHtml = `
        <div class="error-message">
            <i class="fas fa-exclamation-triangle me-2"></i>
            ${message}
        </div>
    `;

    if (containerId) {
        document.getElementById(containerId).innerHTML = errorHtml;
    } else {
        console.error(message);
    }
}

function formatPriority(priority) {
    const priorityClass = {
        'High': 'priority-high',
        'Medium': 'priority-medium',
        'Low': 'priority-low'
    };

    return `<span class="${priorityClass[priority] || ''}">${priority}</span>`;
}

function formatStatus(status) {
    const statusClass = {
        'Open': 'bg-primary',
        'In Progress': 'bg-warning',
        'Closed': 'bg-success',
        'Pending': 'bg-secondary'
        // Si tienes otros estados con nombres largos, puedes mapearlos aquí para asignarles un color
    };

    // 1. Define un largo máximo para el texto del estado (ej. 15 caracteres)
    const maxLength = 15;
    let displayText = status;

    // 2. Si el texto es más largo que el máximo, lo corta y añade "..."
    if (status && status.length > maxLength) {
        displayText = status.substring(0, maxLength) + '...';
    }

    // 3. Devuelve el HTML usando el texto cortado, pero con el texto completo en el 'title' para el tooltip
    return `<span class="badge ${statusClass[status] || 'bg-secondary'}" title="${status}">${displayText}</span>`;
}

function formatRecurrent(isRecurrent) {
    return isRecurrent ?
        '<span class="badge bg-warning">Yes</span>' :
        '<span class="badge bg-success">No</span>';
}

// API functions
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, options);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        // Manejar respuestas vacías o no JSON
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            return await response.json();
        } else if (response.status === 204) { // No Content
            return null;
        } else {
            // Intentar leer como texto si no es JSON
            return await response.text();
        }
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Time period management
function updateTimePeriod(days) {
    currentTimePeriod = days;

    // Update dropdown selection
    const dropdown = document.getElementById('timePeriodSelect');
    if (dropdown) {
        dropdown.value = days;
    }

    updateKPILabels(days);
    
    // Solo cargar datos si ya tenemos datos en caché
    // No hacemos refresh al servidor, solo actualizamos la vista
    loadKPIs();
    loadCharts();
    loadTopRepeatedServices(currentTimePeriod);
}

function updateTimePeriodFromSelect() {
    const dropdown = document.getElementById('timePeriodSelect');
    if (dropdown) {
        const value = dropdown.value;
        const days = value === 'all' ? 'all' : parseInt(value);
        updateTimePeriod(days);
    }
}

function updateKPILabels(days) {
    const periodText = days === 'all' ? 'All Time' : `${days} days`;
    document.getElementById('total-tickets-label').textContent = `Total Tickets (${periodText})`;
    document.getElementById('recurrent-tickets-label').textContent = `Repeated Tickets (${periodText})`;
    document.getElementById('avg-resolution-label').textContent = `Avg. Resolution Time (${periodText})`;
    document.getElementById('first-response-label').textContent = `First Response Time (${periodText})`;
    document.getElementById('repeated-tickets-percentage-label').textContent = `% Repeated Tickets ${periodText}`;
}

// Dashboard functions
async function loadKPIs() {
    try {
        const data = await apiCall(`/api/kpis?days=${currentTimePeriod}`);

        // Función auxiliar para actualizar un elemento solo si existe
        const updateElementText = (id, text) => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = text;
            }
        };

        updateElementText('total-tickets', data.total || 0);
        updateElementText('recurrent-tickets', data.repeated_services || 0);
        updateElementText('avg-resolution-time', data.avg_time_hours ? `${data.avg_time_hours}h` : '-');
        updateElementText('repeated-tickets-percentage', data.repeated_tickets_percentage ? `${data.repeated_tickets_percentage}%` : '-');
        updateElementText('open-tickets', data.open_tickets || 0);
        updateElementText('first-response-time', data.first_response_hours ? `${data.first_response_hours}h` : '-');

    } catch (error) {
        console.error('Failed to load KPIs:', error);
        // El error personalizado se mostrará si la llamada a la API falla.
        // Si solo faltan los elementos HTML, ahora no se mostrará error.
        showError('Failed to load KPI data. Please check your connection and try again.');
    }
}

async function loadCharts() {
    try {
        await Promise.all([
            loadMonthlyEvolutionChart(),
            loadIssueTypeChart(),
            loadTopClientsChart(),
            loadTicketTypeChart()
        ]);
    } catch (error) {
        console.error('Failed to load charts:', error);
    }
}

async function loadTopRepeatedServices(days) {
    const tbody = document.getElementById('top-repeated-services-table').querySelector('tbody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Loading...</td></tr>';

    try {
        // CORRECCIÓN: Llamamos al endpoint correcto que creamos en main.py
        const data = await apiCall(`/api/dashboard-repeat-summary?days=${days}`);

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No repeated services found for this period.</td></tr>';
            return;
        }

        tbody.innerHTML = data.map((item, index) => `
            <tr>
                <td class="text-center">${index + 1}</td>
                <td>${item.service}</td>
                <td>${item.client}</td>
                <td class="text-center fw-bold">${item.count}</td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Failed to load top repeated services:', error);
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-danger">Error loading data.</td></tr>';
    }
}

async function loadMonthlyEvolutionChart() {
    try {
        const data = await apiCall(`/api/charts?name=monthly_evolution&days=${currentTimePeriod}`);

        const ctx = document.getElementById('monthlyEvolutionChart');
        if (!ctx) return;

        const chartInstance = Chart.getChart(ctx);
        if (chartInstance) {
            chartInstance.destroy();
        }

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels || [],
                datasets: [{
                    label: 'Tickets',
                    data: data.data || [],
                    borderColor: chartColors.primary,
                    backgroundColor: chartColors.primary + '20',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: '#E2E8F0'
                        }
                    },
                    x: {
                        grid: {
                            color: '#E2E8F0'
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });
    } catch (error) {
        console.error('Failed to load monthly evolution chart:', error);
    }
}

async function loadTopClientsChart() {
    try {
        const data = await apiCall(`/api/charts?name=top_clients&days=${currentTimePeriod}`);

        const ctx = document.getElementById('topClientsChart');
        if (!ctx) return;

        const chartInstance = Chart.getChart(ctx);
        if (chartInstance) {
            chartInstance.destroy();
        }

        const maxLineLength = 25;
        const wrapText = (label, maxLength) => {
            if (!label) return [''];
            const words = label.split(' ');
            const lines = [];
            let currentLine = '';
            words.forEach(word => {
                if ((currentLine + ' ' + word).trim().length > maxLength) {
                    lines.push(currentLine);
                    currentLine = word;
                } else {
                    currentLine = (currentLine + ' ' + word).trim();
                }
            });
            lines.push(currentLine);
            return lines;
        };
        const wrappedLabels = data.labels.map(label => wrapText(label, maxLineLength));

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: wrappedLabels,
                datasets: [{
                    label: 'Tickets',
                    data: data.data || [],
                    backgroundColor: chartColors.primary,
                    borderColor: chartColors.primary,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: {
                            color: '#E2E8F0'
                        }
                    },
                    y: {
                        grid: {
                            display: false
                        },
                        ticks: {
                           align: 'end',
                           // V  AÑADE ESTA SECCIÓN PARA REDUCIR LA FUENTE  V
                           font: {
                               size: 6 // Puedes ajustar este tamaño (ej. 9, 11)
                           }
                           // ^-------------------------------------------------^
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });
    } catch (error) {
        console.error('Failed to load top clients chart:', error);
    }
}

async function loadIssueTypeChart() {
    try {
        const data = await apiCall(`/api/charts?name=by_issue_type&days=${currentTimePeriod}`);
        if (data.data.length > 20) {
            data.labels = data.labels.slice(0, 20);
            data.data = data.data.slice(0, 20);
        }

        const ctx = document.getElementById('issueTypeChart');
        if (!ctx) return;

        const chartInstance = Chart.getChart(ctx);
        if (chartInstance) {
            chartInstance.destroy();
        }

        const colors = [
            chartColors.primary,
            chartColors.secondary,
            chartColors.accent,
            chartColors.danger,
            chartColors.info
        ];

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels || [],
                datasets: [{
                    label: 'Tickets',
                    data: data.data || [],
                    backgroundColor: colors.slice(0, data.labels?.length || 0),
                    borderColor: colors.slice(0, data.labels?.length || 0),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: '#E2E8F0'
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });
    } catch (error) {
        console.error('Failed to load issue type chart:', error);
    }
}

async function loadTicketTypeChart() {
    try {
        // Pide los datos al nuevo endpoint 'by_ticket_type' que creaste en main.py
        const data = await apiCall(`/api/charts?name=by_ticket_type&days=${currentTimePeriod}`);

        // Apunta al nuevo <canvas> que creaste en index.html
        const ctx = document.getElementById('ticketTypeChart');
        if (!ctx) return;

        // Destruye la gráfica anterior si existe (útil para el botón de refrescar)
        const chartInstance = Chart.getChart(ctx);
        if (chartInstance) {
            chartInstance.destroy();
        }

        // Paleta de colores para las barras
        const colors = [
            '#6366F1', '#EC4899', '#22C55E', '#F59E0B', '#38BDF8', 
            '#8B5CF6', '#D946EF', '#10B981', '#FBBF24', '#60A5FA'
        ];

        // Crea la nueva instancia de la gráfica
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels || [],
                datasets: [{
                    label: 'Tickets',
                    data: data.data || [],
                    backgroundColor: colors,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            // Asegura que el eje Y solo muestre números enteros
                            precision: 0
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false // Oculta la leyenda 'Tickets'
                    }
                }
            }
        });
    } catch (error) {
        console.error('Failed to load ticket type chart:', error);
    }
}

async function loadTopRepeatedServices(days) {
    // PRIMERO, verificamos si la tabla existe en la página actual.
    const tableElement = document.getElementById('top-repeated-services-table');
    if (!tableElement) {
        return; // Si no existe, no hacemos nada y salimos de la función.
    }

    const tbody = tableElement.querySelector('tbody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">Loading...</td></tr>';

    try {
        const data = await apiCall(`/api/dashboard-repeat-summary?days=${days}`);

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">No repeated services found.</td></tr>';
            return;
        }

        tbody.innerHTML = data.map(item => `
            <tr>
                <td>${item.service}</td>
                <td class="text-center fw-bold">${item.count}</td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Failed to load top repeated services:', error);
        tbody.innerHTML = '<tr><td colspan="2" class="text-center text-danger">Error loading data.</td></tr>';
    }
}

// Variable global para almacenar los últimos tickets cargados
let latestTicketsCache = [];

async function loadLatestTickets() {
    try {
        const tickets = await apiCall('/api/search-tickets');
        const tbody = document.querySelector('#latest-tickets-table tbody');

        if (!tbody) return;

        const latestTickets = tickets.slice(0, 5);
        
        // Guardar en caché para exportación
        latestTicketsCache = latestTickets;

        if (latestTickets.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No tickets available</td></tr>';
            return;
        }

        tbody.innerHTML = latestTickets.map(ticket => `
            <tr>
                <td><strong>${ticket.id || '-'}</strong></td>
                <td class="text-truncate" title="${ticket.subject}">${ticket.subject || '-'}</td>
                <td>${ticket.client || '-'}</td>
                <td>${formatPriority(ticket.priority || 'Low')}</td>
                <td>${formatStatus(ticket.status || 'Open')}</td>
                <td><small>${formatDateLocal(ticket.created)}</small></td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Failed to load latest tickets:', error);
        const tbody = document.querySelector('#latest-tickets-table tbody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Failed to load tickets</td></tr>';
        }
    }
}

function exportLatestTicketsToCSV() {
    if (latestTicketsCache.length === 0) {
        alert('No hay tickets para exportar');
        return;
    }

    const headers = ['ID', 'Subject', 'Client', 'Priority', 'Status', 'Created'];

    const csvContent = [
        headers.join(','),
        ...latestTicketsCache.map(ticket => [
            ticket.id || '',
            `"${(ticket.subject || '').replace(/"/g, '""')}"`,
            `"${(ticket.client || '').replace(/"/g, '""')}"`,
            ticket.priority || '',
            `"${(ticket.status || '').replace(/"/g, '""')}"`,
            ticket.created || ''
        ].join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);

    link.setAttribute('href', url);
    link.setAttribute('download', `latest_tickets_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

async function exportAllTicketsToCSV() {
    try {
        // Obtener TODOS los tickets del período actual (30 días + 6 horas)
        const allTickets = await apiCall('/api/search-tickets');
        
        if (allTickets.length === 0) {
            alert('No hay tickets para exportar');
            return;
        }

        const headers = ['ID', 'Subject', 'Client', 'Service', 'Priority', 'Status', 'Created', 'Assigned', 'Recurrent'];

        const csvContent = [
            headers.join(','),
            ...allTickets.map(ticket => [
                ticket.id || '',
                `"${(ticket.subject || '').replace(/"/g, '""')}"`,
                `"${(ticket.client || '').replace(/"/g, '""')}"`,
                `"${(ticket.service || '').replace(/"/g, '""')}"`,
                ticket.priority || '',
                `"${(ticket.status || '').replace(/"/g, '""')}"`,
                ticket.created || '',
                `"${(ticket.assigned || '').replace(/"/g, '""')}"`,
                ticket.recurrent ? 'Yes' : 'No'
            ].join(','))
        ].join('\n');

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);

        link.setAttribute('href', url);
        link.setAttribute('download', `all_tickets_30d_${new Date().toISOString().split('T')[0]}.csv`);
        link.style.visibility = 'hidden';

        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Mostrar notificación de éxito
        showNotification(`${allTickets.length} tickets exportados exitosamente`, 'success');
        
    } catch (error) {
        console.error('Error exporting all tickets:', error);
        alert('Error al exportar los tickets. Por favor intenta de nuevo.');
    }
}

// Helper function to load all dashboard data
async function loadDashboardData() {
    console.log("Cargando datos del dashboard...");
    await Promise.all([
        loadKPIs(),
        loadCharts(),
        loadLatestTickets(),
        loadTopRepeatedServices(currentTimePeriod)
    ]);
    console.log("Datos del dashboard cargados.");
}

// Notification helper
function showNotification(message, type = 'info') {
    const alertContainer = document.getElementById('notification-alert-container');
    if (!alertContainer) return;

    const alertHtml = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
    alertContainer.innerHTML += alertHtml;
}

async function refreshData() {
    console.log("Paso 1: Llamando a /api/refresh para actualizar los datos en el servidor...");

    // Obtener el filtro de días actual
    const daysFilter = document.getElementById('timePeriodSelect')?.value || '30';
    console.log(`[DEBUG] Enviando refresh con filtro de ${daysFilter} días`);

    // Paso 1: Llamar al endpoint de refresh con el parámetro de días como query parameter
    try {
        // Enviamos 'days' como parámetro de URL (query parameter)
        await apiCall(`/api/refresh?days=${daysFilter}`, {
            method: 'POST'
        });
        console.log("Paso 2: El servidor terminó. Ahora pidiendo los datos actualizados para el dashboard.");

        // Paso 2: Actualizar el período de tiempo actual
        currentTimePeriod = daysFilter === 'all' ? 'all' : parseInt(daysFilter);
        
        // Paso 3: Volver a cargar los datos actualizados para el dashboard
        await loadDashboardData();
        showNotification('Dashboard refreshed successfully!', 'success');
    } catch (error) {
        console.error("Error durante el refresh:", error);
        showNotification('Error al actualizar los datos', 'error');
    }
}

// Analysis page functions
async function loadFilterOptions() {
    try {
        filterOptions = await apiCall('/api/filter-options');

        // Populate client selects
        const clientSelects = ['clientSelect', 'clientFilter'];
        clientSelects.forEach(selectId => {
            const select = document.getElementById(selectId);
            if (select && filterOptions.clients) {
                const currentValue = select.value;
                select.innerHTML = '<option value="">All Clients</option>' +
                    filterOptions.clients.map(client =>
                        `<option value="${client}" ${client === currentValue ? 'selected' : ''}>${client}</option>`
                    ).join('');
            }
        });

        // Populate service selects
        const serviceSelects = ['serviceSelect', 'serviceFilter'];
        serviceSelects.forEach(selectId => {
            const select = document.getElementById(selectId);
            if (select && filterOptions.services) {
                const currentValue = select.value;
                select.innerHTML = '<option value="">All Services</option>' +
                    filterOptions.services.map(service =>
                        `<option value="${service}" ${service === currentValue ? 'selected' : ''}>${service}</option>`
                    ).join('');
            }
        });

        // Populate other filters for tickets page
        const statusFilter = document.getElementById('statusFilter');
        if (statusFilter && filterOptions.statuses) {
            statusFilter.innerHTML = '<option value="">All Statuses</option>' +
                filterOptions.statuses.map(status => `<option value="${status}">${status}</option>`).join('');
        }

        const priorityFilter = document.getElementById('priorityFilter');
        if (priorityFilter && filterOptions.priorities) {
            priorityFilter.innerHTML = '<option value="">All Priorities</option>' +
                filterOptions.priorities.map(priority => `<option value="${priority}">${priority}</option>`).join('');
        }

        const assignedFilter = document.getElementById('assignedFilter');
        if (assignedFilter && filterOptions.assigned) {
            assignedFilter.innerHTML = '<option value="">All Assignees</option>' +
                filterOptions.assigned.map(assignee => `<option value="${assignee}">${assignee}</option>`).join('');
        }

    } catch (error) {
        console.error('Failed to load filter options:', error);
    }
}

async function updateAnalysis() {
    try {
        const clientSelect = document.getElementById('clientSelect');
        const serviceSelect = document.getElementById('serviceSelect');
        const searchInput = document.getElementById('searchInput');

        const cliente = clientSelect ? clientSelect.value : '';
        const servicio = serviceSelect ? serviceSelect.value : '';
        const searchValue = searchInput ? searchInput.value.trim() : '';

        console.log('Updating analysis with filters:', { cliente, servicio, searchValue });

        const params = new URLSearchParams();
        if (cliente) params.append('cliente', cliente);
        if (servicio) params.append('servicio', servicio);
        if (searchValue) params.append('search', searchValue);

        // Always load the chart, even without filters (to show all data)
        await loadAltairTimelineChart(params);

        // Load summary data
        try {
            const summaryData = await apiCall(`/api/failure-analysis?${params.toString()}`);
            updateAnalysisSummary(summaryData);
        } catch (summaryError) {
            console.error('Failed to load summary data:', summaryError);
            // Don't fail the whole function if summary fails
        }

    } catch (error) {
        console.error('Failed to update analysis:', error);
        showError('Failed to load analysis data', 'altairTimelineChart');
    }
}


async function loadAltairTimelineChart(params) {
    try {
        const chartContainer = document.getElementById('altairTimelineChart');
        const loadingMessage = document.getElementById('loadingMessage');
        const initialMessage = document.getElementById('initialMessage');

        if (!chartContainer) return;

        // Show loading
        if (initialMessage) initialMessage.style.display = 'none';
        if (loadingMessage) loadingMessage.style.display = 'block';

        const response = await apiCall(`/api/altair-timeline?${params}`);

        // Hide loading
        if (loadingMessage) loadingMessage.style.display = 'none';

        // Display chart
        chartContainer.innerHTML = response.html;

    } catch (error) {
        console.error('Failed to load Altair timeline chart:', error);
        const chartContainer = document.getElementById('altairTimelineChart');
        if (chartContainer) {
            chartContainer.innerHTML = `
                <div class="text-center text-danger p-4">
                    <i class="fas fa-exclamation-triangle fa-2x mb-3"></i>
                    <h5>Error Loading Chart</h5>
                    <p>Failed to load timeline chart. Please try again.</p>
                </div>
            `;
        }
    }
}

function showInitialMessage() {
    const chartContainer = document.getElementById('altairTimelineChart');
    const initialMessage = document.getElementById('initialMessage');

    if (chartContainer && initialMessage) {
        initialMessage.style.display = 'block';
        chartContainer.innerHTML = `
            <div id="initialMessage" class="text-center text-muted py-5">
                <i class="fas fa-search fa-3x mb-3"></i>
                <h5>Select Filters to View Timeline</h5>
                <p>Use the filters above or search to view the service timeline analysis.</p>
            </div>
        `;
    }
}

function updateAnalysisSummary(data) {
    const totalFailures = data.length;
    const highPriorityFailures = data.filter(item => item.priority === 'High').length;

    const totalElement = document.getElementById('totalFailures');
    const highPriorityElement = document.getElementById('highPriorityFailures');

    if (totalElement) totalElement.textContent = totalFailures;
    if (highPriorityElement) highPriorityElement.textContent = highPriorityFailures;

    // Update top issues
    const issueTypes = {};
    data.forEach(item => {
        issueTypes[item.issue] = (issueTypes[item.issue] || 0) + 1;
    });

    const topIssues = Object.entries(issueTypes)
        .sort(([,a], [,b]) => b - a)
        .slice(0, 5);

    const topIssuesContainer = document.getElementById('topIssuesContainer');
    if (topIssuesContainer) {
        if (topIssues.length === 0) {
            topIssuesContainer.innerHTML = '<p class="text-muted">No issues found</p>';
        } else {
            topIssuesContainer.innerHTML = topIssues.map(([issue, count]) => `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="text-truncate">${issue}</span>
                    <span class="badge bg-primary">${count}</span>
                </div>
            `).join('');
        }
    }
}

function clearFilters() {
    const clientSelect = document.getElementById('clientSelect');
    const serviceSelect = document.getElementById('serviceSelect');

    if (clientSelect) clientSelect.value = '';
    if (serviceSelect) serviceSelect.value = '';

    updateAnalysis();
}

function refreshAnalysis() {
    loadAnalysisClients();
}

// Tickets page functions
async function searchTickets() {
    try {
        const params = new URLSearchParams();

        const filters = {
            client: 'clientFilter',
            service: 'serviceFilter',
            status: 'statusFilter',
            priority: 'priorityFilter',
            assigned: 'assignedFilter'
        };

        Object.entries(filters).forEach(([param, elementId]) => {
            const element = document.getElementById(elementId);
            if (element && element.value) {
                params.append(param, element.value);
            }
        });

        // Convertir fechas locales a UTC antes de enviar
        const startDateElement = document.getElementById('dateRangeStart');
        const endDateElement = document.getElementById('dateRangeEnd');
        
        if (startDateElement && startDateElement.value) {
            params.append('start_date', dateToUTC(startDateElement.value));
        }
        if (endDateElement && endDateElement.value) {
            params.append('end_date', dateToUTC(endDateElement.value));
        }
        params.append('sort_by', 'created');
        params.append('sort_order', 'desc');

        currentTickets = await apiCall(`/api/search-tickets?${params}`);
        currentPage = 1;
        displayTickets();

    } catch (error) {
        console.error('Failed to search tickets:', error);
        showError('Failed to search tickets', 'ticketsTable');
    }
}

// Variable para almacenar los tickets filtrados por búsqueda rápida
let filteredTicketsCache = [];

function filterTicketsInRealTime() {
    const searchInput = document.getElementById('quickSearchInput');
    if (!searchInput) return;

    const searchTerm = searchInput.value.toLowerCase().trim();

    // Si no hay término de búsqueda, mostrar todos los tickets actuales
    if (!searchTerm) {
        filteredTicketsCache = [];
        displayTickets();
        return;
    }

    // Filtrar los tickets en tiempo real
    filteredTicketsCache = currentTickets.filter(ticket => {
        // Buscar en ID
        const idMatch = ticket.id.toString().toLowerCase().includes(searchTerm);
        
        // Buscar en Subject
        const subjectMatch = (ticket.subject || '').toLowerCase().includes(searchTerm);
        
        // Buscar en Client
        const clientMatch = (ticket.client || '').toLowerCase().includes(searchTerm);
        
        // Buscar en Service
        const serviceMatch = (ticket.service || '').toLowerCase().includes(searchTerm);
        
        // Buscar en Status
        const statusMatch = (ticket.status || '').toLowerCase().includes(searchTerm);
        
        // Buscar en Priority
        const priorityMatch = (ticket.priority || '').toLowerCase().includes(searchTerm);
        
        // Buscar en Assigned To
        const assignedMatch = (ticket.assigned || '').toLowerCase().includes(searchTerm);
        
        // Buscar en Recurrent (Yes/No)
        const recurrentText = ticket.recurrent ? 'yes' : 'no';
        const recurrentMatch = recurrentText.includes(searchTerm);

        // Retornar true si coincide con algún campo
        return idMatch || subjectMatch || clientMatch || serviceMatch || 
               statusMatch || priorityMatch || assignedMatch || recurrentMatch;
    });

    // Resetear a la primera página cuando se filtra
    currentPage = 1;
    
    // Mostrar los tickets filtrados
    displayTickets();
}

function displayTickets() {
    const tbody = document.querySelector('#ticketsTable tbody');
    const resultsCount = document.getElementById('resultsCount');

    if (!tbody) return;

    // Determinar qué tickets mostrar: filtrados o todos
    const ticketsToDisplay = filteredTicketsCache.length > 0 || document.getElementById('quickSearchInput')?.value.trim() 
        ? filteredTicketsCache 
        : currentTickets;

    // Update results count
    if (resultsCount) {
        resultsCount.textContent = ticketsToDisplay.length;
    }

    if (ticketsToDisplay.length === 0) {
        const searchTerm = document.getElementById('quickSearchInput')?.value.trim();
        const message = searchTerm 
            ? `No tickets found matching "${searchTerm}"`
            : 'No tickets found matching your criteria';
        
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center text-muted py-4">
                    <i class="fas fa-inbox fa-2x mb-2"></i>
                    <br>${message}
                </td>
            </tr>
        `;
        updatePagination(0, 0);
        return;
    }

    // Calculate pagination
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, ticketsToDisplay.length);
    const pageTickets = ticketsToDisplay.slice(startIndex, endIndex);

    // Display tickets
    tbody.innerHTML = pageTickets.map(ticket => `
        <tr>
            <td>${ticket.id}</td>
            <td class="text-truncate" style="max-width: 250px;" title="${ticket.subject}">
                ${ticket.subject}
            </td>
            <td>${ticket.client}</td>
            <td>${ticket.service}</td>
            <td>${formatStatus(ticket.status)}</td>
            <td>${formatPriority(ticket.priority)}</td>
            <td>${formatDateTimeLocal(ticket.created)}</td>
            <td>${ticket.assigned}</td>
            <td>${formatRecurrent(ticket.recurrent)}</td>
        </tr>
    `).join('');

    updatePagination(ticketsToDisplay.length, currentPage);
}

function updatePagination(totalItems, currentPageNum) {
    const pagination = document.getElementById('pagination');
    if (!pagination) return;

    const totalPages = Math.ceil(totalItems / pageSize);

    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let paginationHTML = '';

    // Previous button
    paginationHTML += `
        <li class="page-item ${currentPageNum === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPageNum - 1})">Previous</a>
        </li>
    `;

    // Page numbers
    const startPage = Math.max(1, currentPageNum - 2);
    const endPage = Math.min(totalPages, currentPageNum + 2);

    for (let i = startPage; i <= endPage; i++) {
        paginationHTML += `
            <li class="page-item ${i === currentPageNum ? 'active' : ''}">
                <a class="page-link" href="#" onclick="changePage(${i})">${i}</a>
            </li>
        `;
    }

    // Next button
    paginationHTML += `
        <li class="page-item ${currentPageNum === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPageNum + 1})">Next</a>
        </li>
    `;

    pagination.innerHTML = paginationHTML;
}

function changePage(page) {
    const totalPages = Math.ceil(currentTickets.length / pageSize);
    if (page >= 1 && page <= totalPages) {
        currentPage = page;
        displayTickets();
    }
}

function changePageSize(newPageSize) {
    pageSize = newPageSize;
    currentPage = 1;
    displayTickets();

    // Update active button
    document.querySelectorAll('.btn-group button').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent.trim() === newPageSize.toString()) {
            btn.classList.add('active');
        }
    });
}

function clearAllFilters() {
    const filterIds = [
        'dateRangeStart', 'dateRangeEnd', 'clientFilter',
        'serviceFilter', 'statusFilter', 'priorityFilter', 'assignedFilter', 'quickSearchInput'
    ];

    filterIds.forEach(id => {
        const element = document.getElementById(id);
        if (element) element.value = '';
    });

    // Limpiar el cache de búsqueda rápida
    filteredTicketsCache = [];
    
    searchTickets();
}

function refreshTickets() {
    searchTickets();
}

// Export functionality
function exportToCSV() {
    if (currentTickets.length === 0) {
        alert('No tickets to export');
        return;
    }

    const headers = [
        'ID', 'Subject', 'Client', 'Service', 'Status',
        'Priority', 'Created', 'Closed', 'Assigned To', 'Recurrent'
    ];

    const csvContent = [
        headers.join(','),
        ...currentTickets.map(ticket => [
            ticket.id,
            `"${ticket.subject.replace(/"/g, '""')}"`,
            `"${ticket.client}"`,
            `"${ticket.service}"`,
            `"${ticket.status}"`,
            `"${ticket.priority}"`,
            ticket.created,
            ticket.closed || '',
            `"${ticket.assigned}"`,
            ticket.recurrent ? 'Yes' : 'No'
        ].join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);

    link.setAttribute('href', url);
    link.setAttribute('download', `tickets_export_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Search input handler for analysis page
function handleSearchInput() {
    // Debounce the search to avoid too many API calls
    clearTimeout(window.searchTimeout);
    window.searchTimeout = setTimeout(() => {
        updateAnalysis();
    }, 500);
}

// Chart export functionality
function exportChart(canvasId, chartTitle) {
    try {
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            alert('Chart not found. Please ensure the chart is loaded before exporting.');
            return;
        }

        // Create a new canvas with white background and title
        const exportCanvas = document.createElement('canvas');
        const exportCtx = exportCanvas.getContext('2d');

        // Set canvas size with extra space for title
        const titleHeight = 60;
        const padding = 40;
        exportCanvas.width = canvas.width + (padding * 2);
        exportCanvas.height = canvas.height + titleHeight + (padding * 2);

        // Fill with white background
        exportCtx.fillStyle = '#FFFFFF';
        exportCtx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);

        // Draw title
        exportCtx.fillStyle = '#1E293B';
        exportCtx.font = 'bold 24px Inter, Arial, sans-serif';
        exportCtx.textAlign = 'center';
        exportCtx.fillText(chartTitle, exportCanvas.width / 2, padding + 30);

        // Draw chart
        exportCtx.drawImage(canvas, padding, titleHeight + padding);

        // Download the image
        const link = document.createElement('a');
        const fileName = `${chartTitle.replace(/[^a-zA-Z0-9]/g, '_')}_${new Date().toISOString().split('T')[0]}.png`;
        link.download = fileName;
        link.href = exportCanvas.toDataURL('image/png');

        // Trigger download
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

    } catch (error) {
        console.error('Error exporting chart:', error);
        alert('Error exporting chart. Please try again.');
    }
}

// Global error handler
window.addEventListener('error', function(e) {
    console.error('Global error:', e.error);
});

// Prevent form submission on enter key in search fields
document.addEventListener('DOMContentLoaded', function() {
    const searchInputs = document.querySelectorAll('input[type="date"], select');
    searchInputs.forEach(input => {
        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
            }
        });
    });

    // Initialize dashboard and analysis page when loaded
    loadKPIs();
    loadCharts();
    loadLatestTickets();
    loadTopRepeatedServices(currentTimePeriod); 
    loadFilterOptions();
    showInitialMessage();
    loadRepeatKpiHistoryChart()// Show initial message instead of loading all data

    // Add event listener for search input on tickets page
    const searchButton = document.getElementById('searchTicketsButton');
    if (searchButton) {
        searchButton.addEventListener('click', searchTickets);
    }

    // Handle Enter key press on search input fields
    const ticketSearchInputs = [
        'dateRangeStart', 'dateRangeEnd', 'clientFilter',
        'serviceFilter', 'statusFilter', 'priorityFilter', 'assignedFilter'
    ];
    ticketSearchInputs.forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    searchTickets();
                }
            });
        }
    });
});

// Global state for analysis page


// New Service Analysis functions
async function loadAnalysisClients() {
    try {
        const clientListContainer = document.getElementById('clientList');
        if (!clientListContainer) return;

        // Show loading
        clientListContainer.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-spinner fa-spin fa-2x mb-2"></i>
                <p>Loading clients...</p>
            </div>
        `;

        const clients = await apiCall('/api/analysis-clients');
        allClients = clients;

        if (clients.length === 0) {
            clientListContainer.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-users fa-2x mb-2"></i>
                    <p>No clients found</p>
                </div>
            `;
            return;
        }

        renderClientList(clients);
    } catch (error) {
        console.error('Failed to load clients:', error);
        const clientListContainer = document.getElementById('clientList');
        if (clientListContainer) {
            clientListContainer.innerHTML = `
                <div class="text-center text-danger py-3">
                    <i class="fas fa-exclamation-triangle fa-2x mb-2"></i>
                    <p>Failed to load clients. Error: ${error.message}</p>
                    <button class="btn btn-sm btn-outline-primary mt-2" onclick="loadAnalysisClients()">
                        <i class="fas fa-retry"></i> Retry
                    </button>
                </div>
            `;
        }
    }
}

function renderClientList(clients) {
    const clientListContainer = document.getElementById('clientList');
    if (!clientListContainer) return;

    clientListContainer.innerHTML = clients.map(client => {
        const clientName = typeof client === 'string' ? client : client.name;
        const clientId = typeof client === 'string' ? client : client.name;
        return `
            <div class="form-check client-item" data-client="${clientName}">
                <input class="form-check-input" type="radio" name="clientSelection" id="client_${clientName.replace(/[^a-zA-Z0-9]/g, '_')}" value="${clientName}" onchange="selectClient('${clientName}')">
                <label class="form-check-label" for="client_${clientName.replace(/[^a-zA-Z0-9]/g, '_')}">
                    ${clientName}
                </label>
            </div>
        `;
    }).join('');
}

function filterClients() {
    const searchInput = document.getElementById('clientSearch');
    const searchValue = searchInput ? searchInput.value.toLowerCase() : '';

    const filteredClients = allClients.filter(client => {
        const clientName = typeof client === 'string' ? client : client.name;
        return clientName.toLowerCase().includes(searchValue);
    });

    renderClientList(filteredClients);
}

function clearClientSelection() {
    selectedClient = '';
    selectedServices = [];

    // Clear search input
    const clientSearch = document.getElementById('clientSearch');
    if (clientSearch) clientSearch.value = '';

    // Clear client selection
    const clientRadios = document.querySelectorAll('input[name="clientSelection"]');
    clientRadios.forEach(radio => radio.checked = false);

    // Hide service selection and timeline
    const serviceCard = document.getElementById('serviceSelectionCard');
    const timelineCard = document.getElementById('timelineChartCard');
    const summaryCards = document.getElementById('summaryCards');

    if (serviceCard) serviceCard.style.display = 'none';
    if (timelineCard) timelineCard.style.display = 'none';
    if (summaryCards) summaryCards.style.display = 'none';

    // Reload client list
    renderClientList(allClients);
}

async function selectClient(client) {
    try {
        selectedClient = client;
        selectedServices = [];

        // Update selected client name display
        const selectedClientName = document.getElementById('selectedClientName');
        if (selectedClientName) selectedClientName.textContent = client;

        // Show service selection card
        const serviceCard = document.getElementById('serviceSelectionCard');
        if (serviceCard) serviceCard.style.display = 'block';

        // Load services for this client
        await loadClientServices(client);

        // Hide timeline until services are selected
        const timelineCard = document.getElementById('timelineChartCard');
        if (timelineCard) timelineCard.style.display = 'none';

    } catch (error) {
        console.error('Failed to select client:', error);
    }
}
// Función para cargar el gráfico de historial de KPI de tickets repetidos
async function loadRepeatKpiHistoryChart() {
    try {
        const data = await apiCall(`/api/kpi/repeat_history`);
        const ctx = document.getElementById('repeatKpiHistoryChart');
        if (!ctx) return;

        // Destruir la instancia anterior del gráfico si existe
        const chartInstance = Chart.getChart(ctx);
        if (chartInstance) {
            chartInstance.destroy();
        }

        new Chart(ctx, {
            type: 'bar', // Gráfico combinado de barras y líneas
            data: {
                labels: data.labels || [],
                datasets: [
                    {
                        label: 'Daily %',
                        type: 'bar', // Los datos diarios como barras
                        data: data.daily_percentage || [],
                        backgroundColor: chartColors.primary + '40', // Azul semitransparente
                        borderColor: chartColors.primary + '80',
                        borderWidth: 1,
                        order: 2 // Las barras se dibujan detrás de la línea
                    },
                    {
                        label: '7-Day Moving Average',
                        type: 'line', // La media móvil como una línea
                        data: data.moving_average || [],
                        borderColor: chartColors.danger, // Rojo para destacar
                        backgroundColor: chartColors.danger + '20',
                        borderWidth: 2.5,
                        pointRadius: 0, // Sin puntos para una línea suave
                        tension: 0.4, // Curva suave
                        fill: true,
                        order: 1 // La línea se dibuja encima de las barras
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return value + '%'; // Añadir símbolo de % al eje Y
                            }
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 0,
                            minRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 15 // Mostrar menos etiquetas en el eje X para que no se saturen
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                    }
                }
            }
        });
    } catch (error) {
        console.error('Failed to load KPI history chart:', error);
    }
}

async function loadClientServices(client) {
    try {
        const serviceListContainer = document.getElementById('serviceList');
        if (!serviceListContainer) return;

        // Show loading
        serviceListContainer.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-spinner fa-spin fa-2x mb-2"></i>
                <p>Loading services...</p>
            </div>
        `;

        const services = await apiCall(`/api/client-services/${encodeURIComponent(client)}`);
        clientServices[client] = services;

        if (services.length === 0) {
            serviceListContainer.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-cog fa-2x mb-2"></i>
                    <p>No services found for this client</p>
                </div>
            `;
            return;
        }

        renderServiceList(services);
    } catch (error) {
        console.error('Failed to load services:', error);
        const serviceListContainer = document.getElementById('serviceList');
        if (serviceListContainer) {
            serviceListContainer.innerHTML = `
                <div class="text-center text-danger py-3">
                    <i class="fas fa-exclamation-triangle fa-2x mb-2"></i>
                    <p>Failed to load services</p>
                </div>
            `;
        }
    }
}

function renderServiceList(services) {
    const serviceListContainer = document.getElementById('serviceList');
    if (!serviceListContainer) return;

    serviceListContainer.innerHTML = services.map(service => `
        <div class="form-check service-item" data-service="${service}">
            <input class="form-check-input" type="checkbox" id="service_${service.replace(/[^a-zA-Z0-9]/g, '_')}" value="${service}" onchange="toggleService('${service}')">
            <label class="form-check-label" for="service_${service.replace(/[^a-zA-Z0-9]/g, '_')}">
                ${service}
            </label>
        </div>
    `).join('');
}

function filterServices() {
    const searchInput = document.getElementById('serviceSearch');
    const searchValue = searchInput ? searchInput.value.toLowerCase() : '';

    const services = clientServices[selectedClient] || [];
    const filteredServices = services.filter(service => 
        service.toLowerCase().includes(searchValue)
    );

    renderServiceList(filteredServices);

    // Re-check previously selected services
    selectedServices.forEach(service => {
        const checkbox = document.getElementById(`service_${service.replace(/[^a-zA-Z0-9]/g, '_')}`);
        if (checkbox) checkbox.checked = true;
    });
}

function toggleService(service) {
    const checkbox = document.getElementById(`service_${service.replace(/[^a-zA-Z0-9]/g, '_')}`);
    if (!checkbox) return;

    if (checkbox.checked) {
        if (!selectedServices.includes(service)) {
            selectedServices.push(service);
        }
    } else {
        selectedServices = selectedServices.filter(s => s !== service);
    }
}

function selectAllServices() {
    const services = clientServices[selectedClient] || [];
    selectedServices = [...services];

    // Check all checkboxes
    services.forEach(service => {
        const checkbox = document.getElementById(`service_${service.replace(/[^a-zA-Z0-9]/g, '_')}`);
        if (checkbox) checkbox.checked = true;
    });
}

function clearServiceSelection() {
    selectedServices = [];

    // Clear search input
    const serviceSearch = document.getElementById('serviceSearch');
    if (serviceSearch) serviceSearch.value = '';

    // Uncheck all checkboxes
    const serviceCheckboxes = document.querySelectorAll('#serviceList input[type="checkbox"]');
    serviceCheckboxes.forEach(checkbox => checkbox.checked = false);

    // Re-render service list
    if (selectedClient && clientServices[selectedClient]) {
        renderServiceList(clientServices[selectedClient]);
    }
}

async function generateTimeline() {
    if (!selectedClient || selectedServices.length === 0) {
        alert('Please select a client and at least one service to generate the timeline.');
        return;
    }

    try {
        // Show timeline card and loading
        const timelineCard = document.getElementById('timelineChartCard');
        const loadingMessage = document.getElementById('timelineLoadingMessage');
        const summaryCards = document.getElementById('summaryCards');

        if (timelineCard) timelineCard.style.display = 'block';
        if (loadingMessage) loadingMessage.style.display = 'block';

        // Build API parameters - use the correct parameter format that your API expects
        const params = new URLSearchParams();
        params.append('cliente', selectedClient);
        selectedServices.forEach(service => {
            params.append('servicio', service);
        });

        // Make API call
        const response = await apiCall(`/api/altair-timeline?${params.toString()}`);

        // Hide loading
        if (loadingMessage) loadingMessage.style.display = 'none';

        // Display chart - create a new container to ensure proper rendering
        const chartContainer = document.getElementById('altairTimelineChart');
        if (chartContainer && response.html) {
            // Clear the container first
            chartContainer.innerHTML = '';

            // Create a temporary div to parse the HTML
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = response.html;

            // Move all content to the chart container
            while (tempDiv.firstChild) {
                chartContainer.appendChild(tempDiv.firstChild);
            }

            // Force re-execution of any Vega/Altair scripts in the new HTML
            const scripts = chartContainer.querySelectorAll('script');
            scripts.forEach(script => {
                if (script.textContent.includes('vegaEmbed') || script.textContent.includes('vega')) {
                    try {
                        eval(script.textContent);
                    } catch (e) {
                        console.error('Error executing chart script:', e);
                    }
                }
            });
        }

        // Show summary cards and calculate actual statistics
        if (summaryCards) {
            summaryCards.style.display = 'flex';

            // Calculate actual statistics from the filtered data
            try {
                const params = new URLSearchParams();
                params.append('client', selectedClient);
                selectedServices.forEach(service => {
                    params.append('service', service);
                });

                // Get filtered tickets data for statistics
                apiCall(`/api/search-tickets?${params.toString()}`).then(tickets => {
                    const totalTickets = document.getElementById('totalTickets');
                    const highPriorityTickets = document.getElementById('highPriorityTickets');
                    const avgResolutionTime = document.getElementById('avgResolutionTime');

                    if (totalTickets) totalTickets.textContent = tickets.length || 0;

                    const highPriorityCount = tickets.filter(t => t.priority === 'High').length;
                    if (highPriorityTickets) highPriorityTickets.textContent = highPriorityCount || 0;

                    // Calculate average resolution time for closed tickets
                    const closedTickets = tickets.filter(t => t.closed);
                    if (closedTickets.length > 0) {
                        const totalResolutionTime = closedTickets.reduce((acc, ticket) => {
                            if (ticket.created && ticket.closed) {
                                const created = new Date(ticket.created);
                                const closed = new Date(ticket.closed);
                                const diffHours = (closed - created) / (1000 * 60 * 60);
                                return acc + diffHours;
                            }
                            return acc;
                        }, 0);
                        const avgHours = totalResolutionTime / closedTickets.length;
                        if (avgResolutionTime) {
                            avgResolutionTime.textContent = `${Math.round(avgHours)}h`;
                        }
                    } else {
                        if (avgResolutionTime) avgResolutionTime.textContent = '-';
                    }
                }).catch(error => {
                    console.error('Error calculating statistics:', error);
                    const totalTickets = document.getElementById('totalTickets');
                    const highPriorityTickets = document.getElementById('highPriorityTickets');
                    const avgResolutionTime = document.getElementById('avgResolutionTime');

                    if (totalTickets) totalTickets.textContent = '-';
                    if (highPriorityTickets) highPriorityTickets.textContent = '-';
                    if (avgResolutionTime) avgResolutionTime.textContent = '-';
                });
            } catch (error) {
                console.error('Error setting up statistics calculation:', error);
            }
        }

    } catch (error) {
        console.error('Failed to generate timeline:', error);

        const loadingMessage = document.getElementById('timelineLoadingMessage');
        if (loadingMessage) loadingMessage.style.display = 'none';

        const chartContainer = document.getElementById('altairTimelineChart');
        if (chartContainer) {
            chartContainer.innerHTML = `
                <div class="text-center text-danger p-4">
                    <i class="fas fa-exclamation-triangle fa-2x mb-3"></i>
                    <h5>Error Generating Timeline</h5>
                    <p>Failed to generate timeline. Error: ${error.message}</p>
                    <button class="btn btn-outline-primary mt-2" onclick="generateTimeline()">
                        <i class="fas fa-retry"></i> Try Again
                    </button>
                </div>
            `;
        }
    }
}

function exportTimelineData() {
    if (!selectedClient || selectedServices.length === 0) {
        alert('Please generate a timeline first before exporting data.');
        return;
    }

    try {
        // Multiple strategies to find and export the chart
        let exported = false;

        // Strategy 1: Look for canvas element directly
        const canvas = document.querySelector('#altairTimelineChart canvas');
        if (canvas && !exported) {
            try {
                const link = document.createElement('a');
                link.download = `timeline_${selectedClient}_${new Date().toISOString().split('T')[0]}.png`;
                link.href = canvas.toDataURL('image/png');
                link.click();
                exported = true;
                return;
            } catch (canvasError) {
                console.warn('Canvas export failed:', canvasError);
            }
        }

        // Strategy 2: Look for SVG element and convert to canvas
        const svg = document.querySelector('#altairTimelineChart svg');
        if (svg && !exported) {
            try {
                const svgData = new XMLSerializer().serializeToString(svg);
                const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
                const svgUrl = URL.createObjectURL(svgBlob);

                const img = new Image();
                img.onload = function() {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');
                    canvas.width = img.width || svg.getBoundingClientRect().width;
                    canvas.height = img.height || svg.getBoundingClientRect().height;

                    ctx.fillStyle = 'white';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.drawImage(img, 0, 0);

                    const link = document.createElement('a');
                    link.download = `timeline_${selectedClient}_${new Date().toISOString().split('T')[0]}.png`;
                    link.href = canvas.toDataURL('image/png');
                    link.click();

                    URL.revokeObjectURL(svgUrl);
                };
                img.src = svgUrl;
                exported = true;
                return;
            } catch (svgError) {
                console.warn('SVG export failed:', svgError);
            }
        }

        // Strategy 3: Try to access Vega view through different methods
        const vegaEmbeds = document.querySelectorAll('#altairTimelineChart .vega-embed, #altairTimelineChart [id*="vis"]');
        for (let vegaEmbed of vegaEmbeds) {
            if (exported) break;

            try {
                // Try multiple properties that might contain the view
                const view = vegaEmbed._view || vegaEmbed.view || vegaEmbed.__vega_view__ || vegaEmbed.vega_view;

                if (view && view.toImageURL) {
                    view.toImageURL('png', 2).then(url => {
                        const link = document.createElement('a');
                        link.download = `timeline_${selectedClient}_${new Date().toISOString().split('T')[0]}.png`;
                        link.href = url;
                        link.click();
                    }).catch(error => {
                        console.warn('Vega export failed:', error);
                    });
                    exported = true;
                    return;
                }
            } catch (vegaError) {
                console.warn('Vega view access failed:', vegaError);
            }
        }

        // Strategy 4: HTML to canvas conversion (last resort)
        if (!exported) {
            try {
                const chartContainer = document.getElementById('altairTimelineChart');
                if (chartContainer) {
                    // Use html2canvas if available, otherwise show fallback message
                    if (typeof html2canvas !== 'undefined') {
                        html2canvas(chartContainer).then(canvas => {
                            const link = document.createElement('a');
                            link.download = `timeline_${selectedClient}_${new Date().toISOString().split('T')[0]}.png`;
                            link.href = canvas.toDataURL('image/png');
                            link.click();
                        });
                    } else {
                        // Fallback: create a simple text file with chart data info
                        const exportData = `Timeline Export for ${selectedClient}\nServices: ${selectedServices.join(', ')}\nExported on: ${new Date().toISOString()}\n\nNote: Visual export not available. Please use browser's print function to save the chart as PDF.`;
                        const blob = new Blob([exportData], { type: 'text/plain' });
                        const link = document.createElement('a');
                        link.download = `timeline_${selectedClient}_${new Date().toISOString().split('T')[0]}.txt`;
                        link.href = URL.createObjectURL(blob);
                        link.click();

                        alert('Chart exported as text file. For visual export, please use your browser\'s print function and save as PDF.');
                    }
                }
            } catch (fallbackError) {
                console.error('All export strategies failed:', fallbackError);
                alert('Unable to export chart. Please try using your browser\'s print function to save as PDF.');
            }
        }

    } catch (error) {
        console.error('Export error:', error);
        alert('Error exporting chart. Please try using your browser\'s print function to save as PDF.');
    }
}

async function viewInNewTab() {
    if (!selectedClient || selectedServices.length === 0) {
        alert('Please generate a timeline first before viewing in new tab.');
        return;
    }

    try {
        // Construir la URL con los mismos filtros que el gráfico actual
        const params = new URLSearchParams();
        params.append('cliente', selectedClient);
        selectedServices.forEach(service => params.append('servicio', service));

        // Llamar al nuevo endpoint para obtener el HTML del gráfico optimizado
        const response = await fetch(`/api/altair-timeline-new-tab?${params.toString()}`);
        if (!response.ok) {
            throw new Error('Failed to fetch optimized chart for new tab.');
        }
        const data = await response.json();
        const chartHTML = data.html;

        if (!chartHTML) {
            alert('No chart available to view.');
            return;
        }

        // Create a complete HTML document for the new tab
        const fullHTML = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Timeline - ${selectedClient}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        html, body {
            height: 100%;
            font-family: 'Inter', sans-serif;
            background-color: #f8f9fa;
            display: grid; /* Usamos CSS Grid */
            grid-template-rows: auto 1fr;
        }
        .full-container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            width: 100vw;
            padding: 10px;
        }
        .header {
            flex-shrink: 0;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 15px 20px;
            margin-bottom: 10px;
            text-align: center;
        }
        .header h2 {
            margin: 0 0 10px 0;
            font-size: 1.5rem;
            color: #1E293B;
        }
        .info {
            background-color: #e3f2fd;
            padding: 8px 12px;
            border-radius: 4px;
            margin-bottom: 10px;
            border-left: 4px solid #2196f3;
            font-size: 0.9rem;
        }
        .services-list {
            font-size: 0.85em;
            color: #666;
            margin-top: 5px;
        }
        .chart-container {
            flex-grow: 1; /* Ocupa el espacio restante */
            overflow: auto; /* Permite scroll solo en esta área */
            padding: 20px;
            background: white;
            min-width: 1400px; /* Ancho mínimo para el contenedor */
        }
        .chart-container > div {
            width: 100% !important;
            height: 100% !important;
        }
        .vega-embed {
            width: 100% !important;
            height: 100% !important;
        }
        .vega-embed details {
            display: none !important;
        }
        svg {
            width: 100% !important;
            height: auto !important;
            min-height: 600px !important;
        }
        .vega-embed .vega-actions {
            display: none !important;
        }
        .vega-embed .role-legend {
            font-size: 12px !important;
        }
        .vega-embed .role-legend-title {
            font-size: 14px !important;
            font-weight: 600 !important;
            margin-bottom: 5px !important;
        }
        .vega-embed .role-legend-symbol {
            width: 12px !important;
            height: 12px !important;
        }
        .vega-embed .role-legend-label {
            font-size: 12px !important;
            margin-left: 5px !important;
        }
        .vega-embed .role-axis-label {
            font-size: 11px !important;
        }
        .vega-embed .role-axis-title {
            font-size: 13px !important;
            font-weight: 500 !important;
        }
        .vega-embed {
            text-align: left !important;
        }
        .vega-embed svg {
            margin-left: 0 !important;
        }
        .vega-embed svg > g {
            transform: translateX(10px) !important;
        }
        .vega-embed .role-legend > .role-legend-entry {
            margin: 2px 0 !important;
            padding: 1px 0 !important;
        }
        .marks {
            image-rendering: -webkit-optimize-contrast;
            image-rendering: optimize-contrast;
            image-rendering: crisp-edges;
        }
        .vega-embed .role-legend-title,
        .vega-embed .role-legend-label,
        .vega-embed .role-axis-title,
        .vega-embed .role-axis-label {
            color: #1E293B !important;
        }
    </style>
</head>
<body>
    <div class="full-container">
        <div class="header">
            <h2>Timeline de Servicios - ${selectedClient}</h2>
                <div class="info">
                    <strong>Servicios incluidos:</strong>
                    <div class="services-list">${selectedServices.join(', ')}</div>
                </div>
            <small class="text-muted">Generado el: ${new Date().toLocaleString()}</small>
        </div>
        <div class="chart-container">
            ${chartHTML}
        </div>
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(() => {
                const chartContainer = document.querySelector('.chart-container');
                const vegaEmbeds = document.querySelectorAll('.vega-embed');

                vegaEmbeds.forEach(embed => {
                    embed.style.width = '100%';
                    embed.style.height = '100%';
                });

                const scripts = document.querySelectorAll('script');
                scripts.forEach(script => {
                    if (script.textContent.includes('vegaEmbed') || script.textContent.includes('vega')) {
                        try {
                            eval(script.textContent);
                        } catch (e) {
                            console.error('Error executing chart script:', e);
                        }
                    }
                });

                setTimeout(() => {
                    window.dispatchEvent(new Event('resize'));
                }, 500);
            }, 100);
        });

        window.addEventListener('resize', function() {
            const vegaEmbeds = document.querySelectorAll('.vega-embed');
            vegaEmbeds.forEach(embed => {
                embed.style.width = '100%';
                embed.style.height = '100%';
            });
        });
    </script>
</body>
</html>`;

        // Open the chart in a new tab
        const newTab = window.open('', '_blank');
        if (newTab) {
            newTab.document.write(fullHTML);
            newTab.document.close();

            // Set a more descriptive title for the new tab
            newTab.document.title = `Timeline - ${selectedClient} - ${selectedServices.length} servicios`;
        } else {
            alert('No se pudo abrir una nueva pestaña. Por favor verifica que los popups estén habilitados para este sitio.');
        }

    } catch (error) {
        console.error('Error opening chart in new tab:', error);
        alert('Error al abrir el gráfico en nueva pestaña: ' + error.message);
    }
}