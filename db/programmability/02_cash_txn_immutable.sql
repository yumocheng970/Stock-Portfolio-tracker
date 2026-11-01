-- =====================================================================
-- Programmability 2: cash transactions are insert-only
-- To fix a mistake, record an opposite transaction instead.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_cash_txn_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN 

	-- Exception: a DELETE caused by deleting the portfolio (ON DELETE CASCADE).
   	-- By the time this runs, the parent portfolio row is already gone.
	IF TG_OP = 'DELETE'
		AND NOT EXISTS (SELECT 1 FROM portfolio
				WHERE portfolio_id = OLD.portfolio_id) THEN
		RETURN OLD;
	END IF;


	RAISE EXCEPTION 'Cash transactions cannot be changed or deleted'
		USING ERRCODE	= 'check_violation',
			CONSTRAINT = 'trg_cash_txn_immutable',
			DETAIL	   = format('Cash transaction %s: %s of %s', 
						OLD.cash_txn_id, OLD.txn_type, OLD.amount),
			HINT		=   'Record an opposite transaction instead.';
END;
$$;

CREATE OR REPLACE TRIGGER trg_cash_txn_immutable
	BEFORE UPDATE OR DELETE ON cash_transaction
	FOR EACH ROW
	EXECUTE FUNCTION fn_cash_txn_immutable();

