{#- is_incremental() interroge la base pour savoir si la table existe. La variable
    compilation_hors_ligne permet de compiler le projet pour une autre plateforme sans connexion. -#}
{% macro est_incremental() %}
    {% if var('compilation_hors_ligne', false) %}
        {{ return(false) }}
    {% endif %}
    {{ return(is_incremental()) }}
{% endmacro %}
