# frontend 生产镜像：多阶段构建。
# build 阶段 node:22-alpine 产出 dist，运行阶段 nginx:alpine 只托管静态产物与反代，
# 最终镜像不含 node 与源码（体积与攻击面都小）。

FROM node:22-alpine AS build

WORKDIR /app

# 先只拷 manifest 装依赖：lockfile 不变则这一层永远命中缓存。
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# package.json 的 build = npm run typecheck && vite build —— 类型错误即构建失败，
# 等价于把前端门禁（typecheck）前移进镜像构建。
RUN npm run build


FROM nginx:alpine

# 只搬构建产物与自定义反代配置；覆盖镜像自带的 default.conf。
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
