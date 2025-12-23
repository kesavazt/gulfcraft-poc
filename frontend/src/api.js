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

export const sendMessage = async (message, conversationId) => {
    const response = await api.post('/chat', { message, conversation_id: conversationId });
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

export default api;
