# Isolated QA fixture only. Production connects to the existing MinIO service.
# Build this historical release from its immutable source commit for repeatable CI.
FROM golang:1.26.7-alpine AS build
ENV GOTOOLCHAIN=local GOMAXPROCS=2 MINIO_RELEASE=RELEASE
RUN apk add --no-cache git
WORKDIR /src
RUN git init && git remote add origin https://github.com/minio/minio.git && \
    git fetch --depth 1 origin 01ce918d8279a20e4706b96a64396146894adee4 && git checkout FETCH_HEAD
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -p 2 -trimpath \
    -ldflags "$(go run buildscripts/gen-ldflags.go 2025-09-07T16:13:09Z)" -o /out/minio .

FROM alpine:3.23
RUN apk upgrade --no-cache && apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /licenses/minio.txt
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="07c3a429bfed433e49018cb0f78a52145d4bedeb" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV MINIO_UPDATE=off
EXPOSE 9000
ENTRYPOINT ["minio"]
CMD ["server", "/data"]
