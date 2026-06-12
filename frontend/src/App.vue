<template>
  <div id="app">
    <!-- 
      router-view 是路由出口
      当访问 /login 时，这里显示 Login.vue
      当访问 / 时，这里显示 Home.vue 
    -->
    <router-view />
  </div>
</template>

<script setup>
// 可以在这里定义一些全局的状态或逻辑，例如初始化检查
</script>

<style>
/* 全局样式 */
body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
  background-color: #f5f5f5;
}

#app {
  width: 100%;
  height: 100vh;
}
</style>