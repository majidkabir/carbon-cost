package legacy

import (
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// PriceWithRoute is PriceWith with the route facts Calculate sets.
func PriceWithRoute(res sootcase.Result, tables []rates.Table, fd *ferries.Data, req Request, date time.Time,
	roadKm map[string]roads.Km, spans map[string][][2]float64, origin string) (Response, error) {
	req.roadKm, req.spans, req.origin = roadKm, spans, origin
	return PriceWith(res, tables, fd, req, date)
}
