/* Simulates network latency while the services return mock data.
   Delete together with the mock data once real API calls exist. */
export const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
