FROM golang:1.24 AS build
WORKDIR /src
COPY go.mod ./
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=$(cat RELEASE)" -o /carbon-cost ./cmd/carbon-cost

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /carbon-cost /carbon-cost
ENV ADDR=:8090
EXPOSE 8090
ENTRYPOINT ["/carbon-cost"]
CMD ["serve"]
