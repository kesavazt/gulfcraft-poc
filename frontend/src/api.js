import axios from 'axios';

const API_URL = 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

export const login = async (username, password) => {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/token', formData);
    return response.data;
};

export const register = async (username, password, role = 'user') => {
    const response = await api.post('/auth/register', { username, password, role });
    return response.data;
};

export const sendMessage = async (message, conversationId, state = null) => {
    const response = await api.post('/chat', { message, conversation_id: conversationId, state });
    return response.data;
};

export const getHistory = async (conversationId) => {
    const response = await api.get(`/chat/history/${conversationId}`);
    return response.data;
};

export const getRequests = async () => {
    const response = await api.get('/requests');
    return response.data;
};

export const getUser = async () => {
    const response = await api.get('/users/me');
    return response.data;
};

export const searchProducts = async (query) => {
    const response = await api.get(`/products/search?q=${query}`);
    return response.data;
};

export const addLineItem = async (jobId, itemData) => {
    const response = await api.post(`/requests/${jobId}/items`, itemData);
    return response.data;
};

export const deleteLineItem = async (jobId, itemId) => {
    const response = await api.delete(`/requests/${jobId}/items/${itemId}`);
    return response.data;
};

export const updateLineItem = async (jobId, itemId, data) => {
    const response = await api.put(`/requests/${jobId}/items/${itemId}`, data);
    return response.data;
};

export const approveJob = async (jobId) => {
    const response = await api.post(`/requests/${jobId}/approve`);
    return response.data;
};

export const downloadFile = (downloadUrl) => {
    // Create a temporary link to trigger the download
    const token = localStorage.getItem('token');
    const cacheBust = `cb=${Date.now()}`;
    const separator = downloadUrl.includes('?') ? '&' : '?';
    const fullUrl = `${API_URL}${downloadUrl}${separator}${cacheBust}`;

    // Use fetch with auth header to download the file
    fetch(fullUrl, {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    })
        .then(response => {
            if (!response.ok) {
                throw new Error('Download failed');
            }
            // Get filename from Content-Disposition header or URL
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'costing_sheet.xlsx';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="?(.+)"?/);
                if (match) {
                    filename = match[1];
                }
            } else {
                // Extract from URL
                const urlParts = downloadUrl.split('/');
                filename = urlParts[urlParts.length - 1] || filename;
            }
            return response.blob().then(blob => ({ blob, filename }));
        })
        .then(({ blob, filename }) => {
            // Create a download link and trigger it
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            console.log('Download completed:', filename);
        })
        .catch(error => {
            console.error('Download error:', error);
        });
};

export default api;
