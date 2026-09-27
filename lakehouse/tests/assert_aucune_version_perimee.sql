-- Une version tardive (date_maj antérieure) ne doit jamais remplacer la version courante.
select c.client_id
from {{ ref('silver_clients') }} as c
inner join {{ source('bronze', 'clients') }} as b
    on c.client_id = b.client_id
where cast(b.date_maj as date) > c.date_maj
