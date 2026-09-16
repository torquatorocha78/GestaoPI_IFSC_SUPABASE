-- MIGRATION: Fix data_inicio_extraordinario calculation
-- Issue: SQL calculated data_inicio_extraordinario without +1 day
-- Python adds +1 day, so we need to align SQL with Python logic

-- Step 1: Update existing records
UPDATE obrigacoes_financeiras
SET 
    data_inicio_extraordinario = data_vencimento + INTERVAL '1 day',
    data_fim_extraordinario = data_vencimento + INTERVAL '1 day' + INTERVAL '3 months',
    atualizado_em = now()
WHERE tipo_obrigacao = 'Anuidade'
  AND data_inicio_extraordinario IS NOT NULL
  AND data_vencimento IS NOT NULL
  AND data_inicio_extraordinario = data_vencimento;

-- Step 2: Fix stored procedure
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
    v_inicio_extraordinario date;
    v_fim_extraordinario date;
BEGIN

    SELECT tipo_pi, data_deposito
    INTO v_tipo, v_data_deposito
    FROM ativos_pi
    WHERE id = p_ativo_pi_id;

    IF v_tipo IS NULL THEN
        RAISE EXCEPTION 'Ativo de PI não encontrado: %', p_ativo_pi_id;
    END IF;

    IF v_tipo = 'Patente' THEN
        DELETE FROM obrigacoes_financeiras
        WHERE ativo_pi_id = p_ativo_pi_id;

        FOR i IN 1..20 LOOP
            v_inicio := v_data_deposito + make_interval(years => i - 1);
            v_vencimento := v_inicio + INTERVAL '3 months';
            v_inicio_extraordinario := v_vencimento + INTERVAL '1 day';
            v_fim_extraordinario := v_vencimento + INTERVAL '1 day' + INTERVAL '3 months';

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
                v_inicio_extraordinario,
                v_fim_extraordinario,
                'Pendente'
            );
        END LOOP;

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

-- Step 3: Regenerate all obligations
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
