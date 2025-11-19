# Product Importer (FastAPI + Redis + PostgreSQL)

A lightweight product management system built with **FastAPI**, featuring:

- CSV product upload
- Background processing (uses FastAPI BackgroundTasks)
- PostgreSQL storage (SKU, name, description, active status)
- Filtering, searching & pagination
- Webhooks for product change notifications
- Live updates using SSE (Server Sent Events)
- Minimal HTML UI for Products and Webhook Management


## Live Deployment

**Hosted on Render:**  
https://product-importer-web-f0e9.onrender.com 


## Features

| Feature
| CSV Upload
| Async Progress (SSE)
| Webhooks
| Inline Product CRUD
| Redis Pub/Sub Notifications
| Fully containerized


## Tech Stack

- **FastAPI**
- **PostgreSQL**
- **SQLAlchemy**
- **Redis**
- **BackgroundTasks**
- **SSE (EventSource)**


![UI-1](images/img1.png)

![UI-2](images/img2.png)

![UI-3](images/img3.png)

![UI-4](images/img4.png)