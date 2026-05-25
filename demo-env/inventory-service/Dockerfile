FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY . .
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/inventory-service .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
COPY --from=build /out/inventory-service /inventory-service
EXPOSE 8081
ENTRYPOINT ["/inventory-service"]
