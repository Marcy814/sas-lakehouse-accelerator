/*------------------------------------------------------------------------------
  Programme : 04_indicateurs_fraude.sas
  Objet     : Indicateurs de risque de fraude par sinistre (historique client)
  Entrées   : dwh.sinistres_enrichis
  Sorties   : dwh.indicateurs_fraude
  Règles    : RG-FRA-01 sinistres rapprochés (<= 30 jours)
              RG-FRA-02 sinistre dans les 30 jours suivant l'émission de la police
              RG-FRA-03 déclaration tardive (> 90 jours)
------------------------------------------------------------------------------*/
%include "/sasprog/actuariat/00_autoexec.sas";

proc sort data=dwh.sinistres_enrichis out=work.sinistres_client;
  by client_id date_sinistre sinistre_id;
run;

data dwh.indicateurs_fraude;
  set work.sinistres_client;
  by client_id;
  retain montant_cumul;

  date_precedente = lag(date_sinistre);

  if first.client_id then do;
    nb_sinistres_cumul = 0;
    montant_cumul      = 0;
    date_precedente    = .;
  end;

  nb_sinistres_cumul + 1;
  montant_cumul = montant_cumul + montant_reclame;

  jours_depuis_precedent = date_sinistre - date_precedente;

  flag_rapproche           = (not missing(jours_depuis_precedent) and jours_depuis_precedent <= 30);
  flag_debut_police        = (date_sinistre - date_debut_police <= 30);
  flag_declaration_tardive = (delai_declaration > 90);

  score_risque = 40 * flag_rapproche + 35 * flag_debut_police + 25 * flag_declaration_tardive;

  format date_sinistre yymmdd10.;
  keep client_id sinistre_id date_sinistre nb_sinistres_cumul montant_cumul
       jours_depuis_precedent flag_rapproche flag_debut_police flag_declaration_tardive score_risque;
run;
