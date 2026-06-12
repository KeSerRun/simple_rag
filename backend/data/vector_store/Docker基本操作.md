#### Docker基本操作

##### 辅助命令

> docker version	# 用来查看docker客户端和服务端引擎的版本信息
>
> docker info	# 用来查看docker引擎详细信息
>
> docker --help	# 用来查看帮助信息

##### 镜像(image)命令

>docker image ls	# 列出本地仓库所有镜像
>
>docker images	# 列出本地仓库所有镜像
>
>docker image < 镜像名 >	# 列出本地仓库中指定镜像
>
>docker pull < 镜像名:版本(默认为latest) >	# 从远程仓库下载镜像到本地仓库
>
>docker search < 镜像名 >	# 在远程仓库搜索镜像
>
>docker image rm < 镜像名/镜像id >	# 删除没有运行过的镜像 
>
>docker image rm -f < 镜像名/镜像id >	# 强制删除镜像
>
>docker save < 镜像名/镜像id > -o < 保存的目录/文件名 >	# 以xxx.tar/xxx.img形式备份镜像
>
>docker load -i < 保存的目录/文件名 >	# 恢复镜像

##### 容器(container)命令 

>docker ps	# 查看正在运行的容器
>
>docker ps -a	# 查看所有容器，包括运行，停止
>
>docker ps -a -q / docker ps -qa	# 只查看所有容器id，包括运行，停止
>
>docker run < 镜像名/镜像id >	# 从镜像创建并运行容器
>
>docker run -p 8080(宿主机):8080 < 镜像名/镜像id >	# 从镜像创建并运行容器，端口映射
>
>docker run -p 8080:8080 -d < 镜像名/镜像id >	# 后台从镜像创建并运行容器，端口映射
>
>docker run -p 8080:8080 -d --name < 设置容器名称 > < 镜像名/镜像id >	#后台从镜像创建并运行容器，端口映射，设置容器名称
>
>docker stop < 容器名/容器id >	# 停止容器
>
>docker restart < 容器名/容器id >	# 重新启动容器
>
>docker start < 容器名/容器id >	# 启动容器
>
>docker pause < 容器名/容器id >	# 暂停容器
>
>docker unpause < 容器名/容器id >	# 解除暂停
>
>docker kill < 容器名/容器id >	# 杀死容器
>
>docker rm < 容器名/容器id >	# 删除已经停止的容器
>
>docker rm -f < 容器名/容器id >	# 强制删除容器
>
>docker rm -f $(docker ps -qa)	# 强制删除所有容器
>
>docker logs < 容器名/容器id >	# 查看容器日志
>
>docker logs -t < 容器名/容器id >	# 查看容器日志，查看时间戳
>
>docker logs -f < 容器名/容器id >	# 查看容器日志，实时跟随最新的日志打印
>
>docker logs --tail <数字> < 容器名/容器id >	# 查看容器日志，数字，显示最后多少条
>
>docker exec(执行) -it(在虚拟终端 -t 中以交互模式 -i 进入) < 容器名/容器id > bash	# 进入容器内部
>
>exit	# 退出容器
>
>docker cp < 容器名/容器id:容器中的文件或目录> < 宿主机的目录 >	# 将容器中的文件拷贝到宿主机
>
>docker cp < 容器名/容器id:容器中的文件或目录> < 容器名/容器id: 容器中的文件或目录>	# 容器间的文件拷贝
>
>docker cp < 宿主机的目录 > < 容器名/容器id:容器中的文件或目录>	# 将宿主机的文件拷贝到容器内
>
>docker top < 容器名/容器id >	# 查看容器进程
>
>docker inspect < 容器名/容器id >	# 查看容器详细信息
>
>docker commit -m < 描述信息 > -a < 作者 > < 容器名/容器id > < 镜像名:版本 >	# 将容器打包成镜像

##### 数据卷(volume)命令 

>
>docker run -v < 宿主机的目录:容器中的文件或目录> < 镜像名/镜像id >	# 使用数据卷文件映射
>
>docker run -v < 宿主机的目录:容器中的文件或目录:ro> < 镜像名/镜像id >	# 使用数据卷文件映射，容器内文件设为只读
>
>docker run -v < 别名 :容器中的文件或目录> < 镜像名/镜像id >	# 使用别名进行数据卷文件映射，别名路径不能存在内容
>
>docker volume list	# 查看docker维护的数据卷(包括以别名创建的)
>
>docker volume create < 数据卷别名 >	# 创建docker维护的数据卷
>
>docker volume rm < 数据卷别名 >	# 删除docker维护的数据卷
>
>docker inspect < 数据卷别名 >	# 查看docker维护数据卷的详细信息

##### 网络(network)命令

>curl < 容器ip地址/容器名 > : < 其他容器的应用程序端口 >	# 容器间通过网络进行通信
>
>docker network list	# 查看网桥列表，docker中网桥类型：bridge (默认，可以实现网桥间、容器与主机通信)，host (仅和主机进行通信)，null (不使用任何网络)
>
>docker network create < 网桥名称 > -d < 网桥类型 >	# 创建自定义网桥
>
>docker network inspect < 网桥名称 >	# 查看网桥细节
>
>docker network rm < 网桥名称 >	# 删除指定网桥
>
>docker network prune	# 删除所有未被用到的网桥
>
>docker run -d --network < 网桥名称 > < 镜像名/镜像id >	# 容器创建时绑定网桥
>
>docker network connect < 网桥名称 > < 容器名/容器id >	# 容器创建后绑定网桥

#### Dockerfile介绍

##### Dockerfile功能

通过Dockerfile(镜像描述文件)可以快速构建一个属于自己的镜像

>mkdir docker	# 创建一个docker目录
>
>cd docker	# 将当前目录切换到docker内
>
>touch Dockerfile	#  创建一个Dockerfile文件
>
>vim Dockerfile	# 编辑Dockerfile文件
>
>docker build -f < Dockerfile路径 >  -t < 镜像名:版本 > .	# 构建一个镜像
>
>docker build -t < 镜像名:版本 > . < Dockerfile路径 > 	# 或者

.dockerignore 文件：填写build时所忽略的上下文路径文件

##### Dockerfile的保留指令

| 保留字     | 作用                                                         |
| ---------- | ------------------------------------------------------------ |
| FROM       | 当前镜像是基于哪个镜像的，第一个指令必须是FROM               |
| MAINTAINER | 镜像维护者的姓名和邮箱地址（已废弃）                         |
| RUN        | 构建镜像时需要运行的指令                                     |
| EXPOSE     | 当前容器对外暴露出的端口号                                   |
| WORKDIR    | 指定在创建容器后，终端默认登陆进来的工作目录，一个落脚点     |
| ENV        | 用来在构建镜像过程中设置环境变量，ENV <key> <value>或 ENV key = value |
| ADD        | 将宿主机目录下的文件拷贝进镜像且ADD命令会自动处理URL和解压tar包 |
| COPY       | 类似于ADD，拷贝文件和目录到镜像中<br/>将从构建上下文目录中<原路径>的文件/目录复制到新一层的镜像内的<目标路径>位置 |
| VOLUME     | 容器数据卷，用于数据保存和持久化工作                         |
| CMD        | 指定一个容器启动时要运行的命令<br/>Dockerfile中可以有多个CMD指令，但只有最后一个CMD指令可以接收docker run传参 |
| ENTRYPOINT | 指定一个容器启动时要运行的命令<br/>ENTRYPOINT的目的和CMD一样，都是在指定容器启动程序及其参数 |

##### Dockerfile基本指令

Dockerfile要求一行只能存在一条完整命令，且每一行都必须有一个保留字，如需换行则在行末尾使用反斜线 \

`Dockerfile`

>FROM centos:latest	# 基于centos构建镜像
>
>RUN  yum install -y vim	# 执行容器内构建命令，无人值守(-y)安装vim 
>
>或 RUN ["yum","install","-y","vim"]	# 使用数组形式运行
>
>EXPOSE 15672	# 这个命令仅仅是声明当前容器中服务的端口是谁，没有实际作用
>
>EXPOSE 5672	# 可以声明多个
>
>WORKDIR /path/to/workdir(绝对路径)	# 进入容器后默认目录，可以指定原始镜像中存在的目录，或自动创建不存在的目录
>
>或 WORKDIR a(相对路径)	# 如果指定相对路径，则与原有的默认目录保存相对关系
>
>ADD aa.txt(宿主机文件/或者url) /path/to/workdir(容器目录)	# 将宿主机文件加入到镜像中
>
>或 COPY aa.txt .	# 将宿主机文件加入到默认目录
>
>ENV BASE_PATH = /apps/data	# 设置路径变量
>
>WORKDIR $BASE_PATH	# 使用路径变量
>
>VOLUME $BASE_PATH	# 这里也仅仅是一个声明，告诉使用者容器中可以挂载这个目录到宿主机，没有任何作用
>
>CMD ls $BASE_PATH	# 开机执行指令，不能传递参数
>
>或 CMD ["ls","/apps/data"]	# 支持docker run传参，docker run < 镜像名/镜像id > ls /(覆盖的指令 参数)，适合指令需要改变的情形
>
>或 ENTRYPOINT ["ls","/apps/data"]	# 支持docker run传参，docker run --entrypoint=ls(覆盖的指令) < 镜像名/镜像id > /(覆盖的参数)，适合指令不需要改变，参数需要改变的情形
>
>ENTRYPOINT ["ls"]	# 用来使用容器固定的指令
>
>CMD ["/apps/data"]	# 配合使用，只能在docker run时传参

#### Docker-Compose介绍

##### Docker-Compose引入

1. 为了完成一个完整项目，势必用到N个多个容器配合完成项目中业务开发，一旦引入N多个容器，N多个容器之间就会形成某种依赖，也就意味着某些容器的运行需要其他容器优先启动之后才能正常运行，所以容器的编排就显得至关重要

2. 现在这种方式使用容器，没有办法站在项目的角度将一个项目用到的一组容器划分到一起，日后难点在于项目的多服务器部署，需要项目角度管理用到的一组容器

3. docker-compose.yml就是应用(project)，由一组关联的应用容器组成的一个完整的业务单元

4. 只有linux平台在安装docker时没有安装docker-compose，windows，macos安装docker时自动安装了docker-compose

```bash
sudo curl -L "https://ghproxy.com/https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose	# 在线下载

sudo chmod +x /usr/local/bin/docker-compose	# 赋予执行权限

docker-compose --version	# 验证安装
```

##### yaml文件语法

```yaml
name: "小明"	# 字符串百年来
age: 100	# 数值变量
sex: true	# 布尔值变量
data: null	# 空变量
data: ~	# 空变量
time: 20:16:00	# 时间变量
date: 2022-10-10	# 日期变量
datetime: 2022-10-10 20:16:00	# 时间日期变量

team: ["孙悟空","猪八戒","沙和尚"]	# 数值变量
team:	# 等价于上面写法
  - "孙悟空"
  - "猪八戒"
  - "沙和尚"
 
person: {"name":"xiaoming","age":16}	# 字典变量
person:	# 等价于上面写法
  name: "xiaoming"
  age: 16

message: &message	# 定义引用
  errmsg: "ok"
  status: 0

data:	# 引用变量
  <<:message
```

##### Docker-Compose模板示例

`docker-compose.yaml`

```yaml
version: "3.8" # 指定compose语法版本，注意要与docker的版本兼容

# volumes:
#  mysqlData: # 声明数据卷别名

services:
  mysql:
    # 服务名称
    image: mysql:latest # 镜像名
    restart: always # 设置开机自启
    container_name: mysql # 容器名称
    networks:
      - web # 使用web网络桥
    environment:
      - "MYSQL_ROOT_PASSWORD=12345678"
      - "TZ=Asia/Shanghai"
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci --explicit_defaults_for_timestamp=true
    ports:
      - "3307:3306" # 端口号
    volumes:
      - ./mysql/conf:/etc/mysql/conf.d/ # 数据卷文件映射，同样可以使用数据卷别名
      - ./mysql/data:/var/lib/mysql/
      - ./mysql/logs:/var/log/mysql/
      - ./mysql/initdb:/docker-entrypoint-initdb.d/

  ubuntu1:
    # 创建容器引用
    &ubuntu
    build:
      # 基于dockerfile执行镜像构建命令
      context: ./ # 指定上下文目录
      dockerfile: ./build/Dockerfile # 文件名称[在指定的context的目录下指定那个Dockerfile文件名称]
    image: ubuntu-sshd # 如果同时指定image和build，则会将build后的名称改为image后面的参数
    restart: always
    container_name: ubuntu_1
    tty: true # 伪终端，开发bash访问
    privileged: true # 以特权模式运行
    expose:
      # 用来把服务端口开放给其他服务
      - 22
    ports:
      - "10021:22"
    networks:
      - sys

  ubuntu2:
    <<: *ubuntu # 使用容器引用，后续只需覆盖不同的选项
    container_name: ubuntu_2
    ports:
      - "10022:22"

  ubuntu3:
    <<: *ubuntu
    container_name: ubuntu_3
    ports:
      - "10023:22"

  ubuntu4:
    <<: *ubuntu
    container_name: ubuntu_4
    ports:
      - "10024:22"

networks:
  # 创建自定义网络桥
  web:
  sys:

```

`bash`

>docker-compose ps	# 列出正在运行的服务
>
>docker-compose up -d	# 后台启动docker-compose，必须在docker-compose.yaml文件的目录
>
>docker-compose up -d --build	# 后台启动docker-compose，必须在docker-compose.yaml文件的目录，优先使用dockerfile构建镜像
>
>docker-compose down	# 关闭所有容器，并移除网络
>
>docker-compose rm -f < 服务名称/服务id >	# 强制删除服务
>
>docker-compose top < 服务名称/服务id >	# 查看服务内进程
>
>docker-compose restart -t 20s < 服务名称/服务id >	# 指定20s后重启服务
>
>docker-compose exec < 服务名称/服务id > bash	# 进入服务内部
>
>docker-compose logs < 服务名称/服务id >	# 查看服务日志

#### 运行Mysql服务  

建议: 使用docker hub官方网站，内有镜像，容器使用方法，使用搜索引擎

1. **访问docker hub或者镜像源**

   a. 访问docker hub搜索mysql

   b. 确定版本 默认 latest

2. **下载mysql镜像**

   > docker pull mysql:5.6

3. **运行mysql，开放端口映射(3306)，指定ROOT用户密码 -e(environment环境)，后台运行 -d，指定名称 --name，设置容器自启 --restart=always，设置数据卷映射 -v**

   > docker run -d -p 3306:3306 --name mysql01 \
   >
   > --restart=always \
   >
   > -e MYSQL_ROOT_PASSWORD=123 \
   >
   > -v ./docker/mysql/data:/var/lib/mysql \
   >
   > mysql:5.6

4. **使用*.sql文件形式备份数据**

   a. 利用mysql官方提供的命令 mysqldump

   >docker exec < 容器名/容器id > sh -c 'exec mysqldump --all-databases -u root -p "$MYSQL_ROOT_PASSWORD"' > /some/path/on/your/host/all-databases.sql	#备份全部数据
   
   >docker exec < 容器名/容器id > sh -c 'exec mysqldump --databases < 库名 > -u root -p "$MYSQL_ROOT_PASSWORD"' > /some/path/on/your/host/all-databases.sql	#备份指定库数据
   
   > docker exec < 容器名/容器id > sh -c 'exec mysqldump --no-data --databases < 库名 > -u root -p "$MYSQL_ROOT_PASSWORD"' > /some/path/on/your/host/all-databases.sql	#备份指定库中的结构，不要数据

   b.使用第三方软件如navicate提供的数据备份，导出*.sql

#### 运行Redis服务

1. **访问docker hub或者镜像源确定版本**

2. **通过docker下载redis镜像**

   >docker pull redis:5.0.12

3. **运行redis容器，开放端口映射(6379)，后台运行 -d，指定名称 --name，设置容器自启 --restart=always**

   >docker run -p 6379:6379 -d --name redis01 --restart=always redis:5.0.12

4. **redis支持内存数据持久化**

   a. rdb持久化: 快照持久化，redis服务器将某一时刻数据以快照文件形式写入到磁盘

   b. aof持久化: redis服务器将所有redis客户端的写操作以命令方式记录到日志文件中，AOF更加安全 always everysec

   >docker run -p 6379:6379 -d --name redis01 \
   >
   >--restart=always \
   >
   >redis:5.0.12 \
   >
   >redis-server --appendonly yes	# 将持久化文件生成容器中/data/目录中

   >docker run -p 6379:6379 -d --name redis01 \
   >
   >--restart=always \
   >
   >-v ./docker/redisdata:/data redis:5.0.12 \
   >
   >redis-server --appendonly yes	# 将持久化文件映射到宿主机

5. **自定义配置文件启动redis**

   a. 官网获取指定版本安装包，从中提取*.conf文件并修改

   b. 将*.conf文件放置在宿主机指定目录 (./docker/redisdata:/data)

   c. 挂载配置启动

   >docker run -p 6379:6379 -d --name redis01 \
   >
   >--restart=always \
   >
   >-v ./docker/redisdata:/data redis:5.0.12 redis-server /data/redis.conf	# 注意: 改配置文件bind:0.0.0.0，可以开启远程访问，尾部 [redis-server /data/redis.conf] 是启动时执行的CMD指令，用于启动服务端

#### 运行nginx服务

1. **访问docker hub或者镜像源确定版本**

2. **下载对应镜像**

   >docker pull nginx:1.19.10

3. **运行nginx**

   a. 寻找nginx文件所在目录

   >find / -name nginx	# 搜索指定文件所在目录
   >
   >pwd	# 获取当前目录

   b. 启动nginx 映射端口(80)，后台启动，后台运行 -d，指定名称 --name，设置容器自启 --restart=always，设置数据卷映射 -v
   
   >docker run -p 80:80 -d --name nginx01 \
   >
   >--restart=always \
   >
   >nginx:1.19.10
   
   >docker cp nginx01:/etc/nginx/nginx.conf ./docker/nginx/config/	# 复制配置文件，确保宿主机含有config目录
   >
   >docker cp nginx01:/usr/share/nginx/html ./docker/nginx/	# 复制html文件，确保宿主机含有html目录
   >
   >docker rm -f nginx01	# 移除nginx01
   
   >docker run -p 80:80 -d --name nginx01 \
   >
   >--restart=always \
   >
   >-v ./docker/nginx/config/nginx.conf:/etc/nginx/nginx.conf \
   >
   >-v ./docker/nginx/html:/usr/share/nginx/html \
   >
   >nginx:1.19.10	# 映射配置文件(修改配置文件)，实现负载均衡(反向代理)，映射html目录，实现服务器代理

#### 运行MongoDB服务

1. **拉取MongoDB镜像**

   >docker pull mongo

2. **启动MongoDb容器**

   >docker run --restart=always -d --name mongo01 \
   >
   >-p 27017:27017 \
   >
   >--privileged=true \
   >
   >-e TZ=Asia/Shanghai \
   >
   >-e MONGO_INITDB_ROOT_USERNAME=kww \
   >
   >-e MONGO_INITDB_ROOT_PASSWORD=123 \
   >
   >-v ./docker/mongo/data:/data/db \
   >
   >-v ./docker/mongo/log:/data/log \
   >
   >mongo

3. 容器内启动mongosh服务

   >mongosh -u kww -p 123 --authenticationDatabase admin

#### 运行ES服务

1. **访问docker hub或者镜像源确定版本**

2. **下载镜像**

   >docker pull elasticsearch:6.8.10

3. **运行es**

   a. 启动es 映射端口(9200(http) 9300(tcp))，后台运行 -d，指定名称 --name，设置容器自启 --restart=always，容器数据存储目录(/usr/share/elasticsearch/data)

   >docker run -p 9200:9200 -p 9300:9300 -d --name=es01 \
   >
   >--restart=always \
   >
   >elasticsearch:6.8.10

   等待几秒，保证es已经成功启动

   >docker cp es01:/usr/share/elasticsearch/data ./docker/es	# 复制data文件，确保宿主机含有es目录
   >
   >docker cp es01:/usr/share/elasticsearch/config ./docker/es	# 复制config文件，确保宿主机含有es目录
   >
   >docker rm -f es01	# 移除es01

   >docker run -p 9200:9200 -p 9300:9300 -d --name=es01 \
   >
   >--restart=always \
   >
   >-v ./docker/es/data:/usr/share/elasticsearch/data \
   >
   >-v ./docker/es/config:/usr/share/elasticsearch/config \
   >
   >elasticsearch:6.8.10

   注意: ES启动如果没有指定单机方式运行，默认使用集群方式启动，可能会报错

   >error: max virtual memory areas vm.max_map_count [65530] is too low

   解决方案：在宿主机中执行如下操作

   >yum install -y vim	# CentOS 系统
   >
   >vim /etc/sysctl.conf	# 加入如下配置
   >
   >vm.max_map_count = 262144
   >
   >sysctl -p	# 使配置生效

   b. 设置ik分词器启动

   >a中指令加入-v ./docker/plugins:/usr/share/elasticsearch/plugins	# 确保宿主机具有plugins目录

   下载ik分词器: github或gitee搜索elasticsearch-analysis-ik

   注意: ik分词器必须和es版本一致

   下载并解压缩放入宿主机plugins中

   >yum install -y unzip	# CentOS 系统
   >
   >unzip elasticsearch-analsis-ik-6.8.20.zip

   注意: 解压缩后文件不能散开，需要在plugins中创建一个文件夹，在文件夹中解压缩

   启动时在日志中可以看到analysis-ik已经加载

4. **启动kibana（es客户端）服务**

   a. 访问docker hub或者镜像源确定版本，kibana的版本应该与es保持一致

   b. 下载kibana镜像

   >docker pull kibana:6.8.10

   c. 启动kibana，开发端口(5601)，后台运行 -d，指定名称 --name，设置容器自启 --restart=always，指定kibana连接es服务

   >docker run -p 5601:5601 -d --name kibana --restart=always -e ELASTICSEARCH_URL=http://127.0.0.1:9200 kibana:6.8.10

#### 基于Ubuntu的环境搭建

##### 运行Ubuntu

1. **拉取ubuntu镜像**

   >docker pull ubuntu:25.04

2.  **基于镜像启动容器**

   >docker run --name ubuntu-miniconda --net host -itd ubuntu:25.04	# 注意，必须是-it，否则无法启动

##### Ubuntu配置镜像源

1. **备份原始镜像源 (可跳过)**

   >sudo cp /etc/apt/sources.list /etc/apt/sources.list.back

2. **编辑源文件**

   >sudo vim /etc/apt/sources.list

3. **加入镜像源**

   阿里云镜像源

   >deb https://mirrors.aliyun.com/ubuntu/ focal main restricted universe multiverse
   >
   >deb https://mirrors.aliyun.com/ubuntu/ focal-security main restricted universe multiverse
   >
   >deb https://mirrors.aliyun.com/ubuntu/ focal-updates main restricted universe multiverse
   >
   >deb https://mirrors.aliyun.com/ubuntu/ focal-backports main restricted universe multiverse

   清华镜像源

   >deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ focal main restricted universe multiverse
   >
   >deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ focal-security main restricted universe multiverse
   >
   >deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ focal-updates main restricted universe multiverse
   >
   >deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ focal-backports main restricted universe multiverse

4. **更新系统**

   >sudo apt update
   >
   >sudo apt upgrade

##### 在Ubuntu上搭建Miniconda环境

1. **下载 Miniconda 安装脚本**

   >wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh

2. **添加可执行权限**

   >sudo chmod +x Miniconda3-latest-Linux-x86_64.sh

3. **运行安装脚本**

   >sudo ./Miniconda3-latest-Linux-x86_64.sh

4. **将Miniconda加入PATH路径**

   >vim ~/.bashrc
   >
   >`export PATH="/home/<your_username>/miniconda3/bin:$PATH"`	\# 在文件末尾添加
   >
   >source ~/.bashrc

5. **使用Miniconda**

   >conda create -n < 环境名 > python=< 版本 >	# 创建环境
   >
   >conda activate < 环境名 >	# 激活环境
   >
   >conda deactivate < 环境名 >	# 退出环境
   >
   >conda env	# 查看安装环境
   >
   >conda remove -n < 环境名 > --all	# 删除环境

##### 运行Ubuntu-desktop

1. **拉取桌面镜像**

   >docker pull colinchang/ubuntu-desktop

2. **基于镜像启动容器**

   >docker run -d --name ubuntu-desktop \
   >
   >-p 6901:6901 \
   >
   >-u root \
   >
   >-e VNC_PW=123456 \
   >
   >--shm-size=512m \
   >
   >colinchang/ubuntu-desktop

3. **通过暴露的端口访问容器**

   >访问`https://<your-host>:6901` ， 登录信息如下：
   >
   >用户名: kasm_user
   >
   >密码: 123456







