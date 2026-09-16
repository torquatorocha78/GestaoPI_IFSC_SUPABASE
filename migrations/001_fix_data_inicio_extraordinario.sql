-- ============================================================
-- MIGRATION: Fix data_inicio_extraordinario calculation
-- 
-- Issue: SQL was calculating data_inicio_extraordinario
--        without +1 day, but Python adds +1 day.
--
-- This migration:
-- 1. Updates existing records to add +1 day
-- 2. Fixes the stored procedure to match Python logic
-- ============================================================

-- ============================================================
-- 1. UPDATE EXISTING RECORDS
-- ============================================================
-- For Anuidades (Patentes), add 1 day to data_inicio_extraordinario
UPDATE obrigacoes_financeiras
SET 
    data_inicio_extraordinario = 
        CASE 
            WHEN tipo_obrigacao = 'Anuidade' 
                 AND data_inicio_extraordinario IS NOT NULL
                 AND data_vencimento IS NOT NULL
                 AND data_inicio_extraordinario = data_vencimento
            THEN data_vencimento + INTERVAL '1 day'
            ELSE data_inicio_extraordinario
        END,
    atualizado_em = now()
WHERE tipo_obrigacao = 'Anuidade'
  AND data_inicio_extraordinario IS NOT NULL
  AND data_vencimento IS NOT NULL
  AND data_inicio_extraordinario = data_vencimento;


-- ============================================================
-- 2. FIX STORED PROCEDURE: gerar_obrigacoes_pi()
-- ============================================================
CREATE OR REPLACE FUNCTION gerar_obrigacoes_pi(
    p_ativo_pi_id bigint
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_tipo text;
    v_data_deposito date;
    i integer;
    v_inicio date;
    v_vencimento date;

BEGIN
    -- Busca o ativo
    SELECT
        tipo_pi,
        data_deposito
    INTO
        v_tipo,
        v_data_deposito
    FROM ativos_pi
    WHERE id = p_ativo_pi_id;

    IF v_tipo IS NULL THEN
        RAISE EXCEPTION 'Ativo de PI não encontrado: %', p_ativo_pi_id;
    END IF;

    -- ========================================================
    -- PATENTE: 20 anuidades
    -- ========================================================
    IF v_tipo = 'Patente' THEN
        -- Evita duplicação
        DELETE FROM obrigacoes_financeiras
        WHERE ativo_pi_id = p_ativo_pi_id;

        FOR i IN 1..20 LOOP
            v_inicio := v_data_deposito + make_interval(years => i - 1);
            v_vencimento := v_inicio + INTERVAL '3 months';

            INSERT INTO obrigacoes_financeiras (
                ativo_pi_id,
                tipo_obrigacao,
                numero_obrigacao,
                descricao_pagamento,
                data_inicio,
                data_vencimento,
                data_inicio_extraordinario,
                data_fim_extraordinario,
                status
            )
            VALUES (
                p_ativo_pi_id,
                'Anuidade',
                i,
                'Anuidade ' || i || ' - Patente',
                v_inicio,
                v_vencimento,
                v_vencimento + INTERVAL '1 day',  -- ← FIX: +1 day (aligned with Python)
                v_vencimento + INTERVAL '1 day' + INTERVAL '3 months',
                'Pendente'
            );
        END LOOP;

    -- ========================================================
    -- DESENHO INDUSTRIAL: 4 quinquênios
    -- ========================================================
    ELSIF v_tipo = 'Desenho Industrial' THEN
        DELETE FROM obrigacoes_financeiras
        WHERE ativo_pi_id = p_ativo_pi_id;

        FOR i IN 1..4 LOOP
            v_inicio := v_data_deposito + make_interval(years => i * 5);
            v_vencimento := v_inicio;

            INSERT INTO obrigacoes_financeiras (
                ativo_pi_id,
                tipo_obrigacao,
                numero_obrigacao,
                descricao_pagamento,
                data_inicio,
                data_vencimento,
                status
            )
            VALUES (
                p_ativo_pi_id,
                'Quinquenio',
                i,
                'Quinquênio ' || i || ' - Desenho Industrial',
                v_inicio,
                v_vencimento,
                'Pendente'
            );
        END LOOP;

    -- ========================================================
    -- SOFTWARE: 1 registro
    -- ========================================================
    ELSIF v_tipo = 'Software' THEN
        DELETE FROM obrigacoes_financeiras
        WHERE ativo_pi_id = p_ativo_pi_id;

        INSERT INTO obrigacoes_financeiras (
            ativo_pi_id,
            tipo_obrigacao,
            numero_obrigacao,
            descricao_pagamento,
            data_inicio,
            data_vencimento,
            status
        )
        VALUES (
            p_ativo_pi_id,
            'Registro',
            1,
            'Registro de Software',
            v_data_deposito,
            v_data_deposito,
            'Pendente'
        );
    END IF;

END;
$$;


-- ============================================================
-- 3. REGENERATE ALL OBLIGATIONS (to apply the fix)
-- ============================================================
-- This will recalculate all existing obligations with the corrected logic
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT a.id
        FROM ativos_pi a
        WHERE a.tipo_pi = 'Patente'
    LOOP
        PERFORM gerar_obrigacoes_pi(r.id);
    END LOOP;
END $$;


-- ============================================================
-- 4. VERIFICATION QUERY
-- ============================================================
-- Run this to verify the fix:
-- SELECT
--     a.numero_processo,
--     a.tipo_pi,
--     o.numero_obrigacao,
--     o.descricao_pagamento,
--     o.data_vencimento,
--     o.data_inicio_extraordinario,
--     o.data_fim_extraordinario,
--     (o.data_inicio_extraordinario - o.data_vencimento) as dias_diferenca
-- FROM obrigacoes_financeiras o
-- JOIN ativos_pi a ON a.id = o.ativo_pi_id
-- WHERE a.tipo_pi = 'Patente'
-- ORDER BY a.numero_processo, o.numero_obrigacao;
-- 
-- Expected: data_inicio_extraordinario should be 1 day AFTER data_vencimento
-- ============================================================
