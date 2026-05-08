import axios from 'axios';
import api from './api';

export async function login(username, password) {
  const { data } = await axios.post('/auth/login', { username, password });
  return data;
}

export async function refreshToken(refresh_token) {
  const { data } = await axios.post('/auth/refresh', { refresh_token });
  return data;
}

export async function logout(refreshToken) {
  await api.post('/auth/logout', { refresh_token: refreshToken });
}
