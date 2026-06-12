<template>
  <div class="upload-loading-mask">
    <div class="upload-loading-content">
      <div class="loading-spinner"></div>
      <p>文件上传中...</p>
    </div>
  </div>
</template>

<style scoped>
.upload-loading-mask {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 9999;
}

.upload-loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  background-color: white;
  padding: 30px 40px;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #2563eb;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 15px;
}

.upload-loading-content p {
  margin: 0;
  color: #374151;
  font-size: 16px;
  font-weight: 500;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>