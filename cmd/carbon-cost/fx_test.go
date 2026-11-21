package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

// The tests don't reach the ECB: a trip dated after the embedded rates
// takes the live rates (FX_URL), served here.
func TestMain(m *testing.M) {
	ecb := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
	<Cube><Cube time='2026-11-20'><Cube currency='CHF' rate='0.93'/><Cube currency='CZK' rate='24.3'/></Cube></Cube>
</gesmes:Envelope>`))
	}))
	os.Setenv("FX_URL", ecb.URL)
	code := m.Run()
	ecb.Close()
	os.Exit(code)
}
