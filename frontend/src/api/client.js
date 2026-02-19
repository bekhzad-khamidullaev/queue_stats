import axios from "axios";

const origin = window.location.origin;
const defaultBase =
  import.meta.env.VITE_API_BASE_URL || origin.replace(/5173/, "8080");
const apiBaseUrl = `${defaultBase}/api`;

const client = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000,
  withCredentials: true,
});

export default client;
