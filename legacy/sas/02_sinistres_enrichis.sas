/*------------------------------------------------------------------------------
  Programme : 02_sinistres_enrichis.sas
  Objet     : Sinistres courants enrichis du contexte police et client
  Entrées   : src.polices, src.sinistres, dwh.clients_courants
  Sorties   : dwh.polices_courantes, dwh.sinistres_enrichis
------------------------------------------------------------------------------*/
%include "/sasprog/actuariat/00_autoexec.sas";

proc sort data=src.polices out=work.polices_tries;
  by police_id descending date_maj;
run;

data dwh.polices_courantes;
  set work.polices_tries;
  by police_id;
  if first.police_id;
run;

proc sort data=src.sinistres out=work.sinistres_tries;
  by sinistre_id descending date_maj;
run;

data work.sinistres_courants;
  set work.sinistres_tries;
  by sinistre_id;
  if first.sinistre_id;
run;

proc sql;
  create table work.sinistres_joints as
  select s.sinistre_id,
         s.police_id,
         p.client_id,
         p.produit,
         c.province,
         c.segment,
         p.date_debut as date_debut_police,
         s.date_sinistre,
         s.date_declaration,
         s.type_sinistre,
         s.statut,
         s.montant_reclame,
         s.montant_paye,
         s.date_declaration - s.date_sinistre as delai_declaration
  from work.sinistres_courants as s
       inner join dwh.polices_courantes as p
         on s.police_id = p.police_id
       left join dwh.clients_courants as c
         on p.client_id = c.client_id;
quit;

data dwh.sinistres_enrichis;
  set work.sinistres_joints;
  length tranche_montant $5;

  if montant_paye < 1000 then tranche_montant = 'PETIT';
  else if montant_paye < 10000 then tranche_montant = 'MOYEN';
  else tranche_montant = 'GRAND';

  taux_paiement  = montant_paye / montant_reclame;
  annee_sinistre = year(date_sinistre);

  format taux_paiement percent8.2 date_debut_police date_sinistre date_declaration yymmdd10.;
run;
