import uvicorn

if __name__ == '__main__':
    # Un solo proceso: la cola local y la recuperación de trabajos no son distribuidas.
    uvicorn.run('backend.app:app', host='127.0.0.1', port=8765, workers=1)
