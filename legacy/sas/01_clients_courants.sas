/*------------------------------------------------------------------------------
  Programme : 01_clients_courants.sas
  Objet     : Version courante de chaque client, standardisée pour l'actuariat
  Entrées   : src.clients
  Sorties   : dwh.clients_courants
  Historique: 2012-03 création | 2017-09 ajout tranche_age | 2021-01 segment PME
------------------------------------------------------------------------------*/
%include "/sasprog/actuariat/00_autoexec.sas";

proc sort data=src.clients out=work.clients_tries;
  by client_id descending date_maj;
run;

data work.clients_dedup;
  set work.clients_tries;
  by client_id;
  if first.client_id;
run;

data dwh.clients_courants;
  set work.clients_dedup;
  length tranche_age $5 nom_complet $80;

  province    = upcase(strip(province));
  nom_complet = catx(' ', propcase(prenom), propcase(nom));
  age         = intck('year', date_naissance, &date_ref, 'c');

  if age < 30 then tranche_age = '18-29';
  else if age < 50 then tranche_age = '30-49';
  else if age < 65 then tranche_age = '50-64';
  else tranche_age = '65+';

  format date_naissance date_maj yymmdd10.;
  keep client_id nom_complet date_naissance age tranche_age province ville segment date_maj;
run;
