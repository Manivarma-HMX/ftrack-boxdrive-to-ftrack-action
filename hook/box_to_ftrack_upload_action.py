'''     Box Items to Ftrack v1.0

Description: Gathers shared items from Box Drive and upload
it to Ftrack

Usage: Run Action on a valid Folder
'''
import os
import json
import shutil
import logging
import subprocess

import ftrack
import ftrack_api
from ftrack_action_handler.action import BaseAction

VALID_ENTITIES = ['TypedContext']
TASKS = ['Task', 'Document']

class BoxFtrackTransfer(BaseAction):
    label = "Box Files to Ftrack"
    identifier = "hmx.boxtoftrack.upload.action"
    description = "Retrive files from shared Box link."

    ftrack_log = logging.getLogger(identifier)

    def register(self):
        """Registers the action, subscribing the discover and launch topics."""
        self.session.event_hub.subscribe(
            'topic=ftrack.action.discover and source.user.username={0}'.format(
                self._session.api_user
            ),
            self._discover
        )
        self.session.event_hub.subscribe(
            'topic=ftrack.action.launch and source.user.username={0} '
            'and data.actionIdentifier={1}'.format(
                self._session.api_user, self.identifier
            ),
            self._launch
        )

    def _discover(self, event):
        # Overide discover to inject custom icon

        result = super(BoxFtrackTransfer, self)._discover(event)
        if not result:
            return 

        # return result
        return {
            'items': [{
                'label': self.label,
                'icon': 'https://i.ibb.co/frjbxKc/coloured-upload-from-box.png',
                'description':self.description,
                'actionIdentifier': self.identifier
            }]
        }

    def _create_job(self, event, message):
        '''Return new job from *event*.

        ...note: This function will auto-commit the session.

        '''
        user_id = event['source']['user']['id']
        job = self.session.create(
            'Job',
            {
                'user': self.session.get('User', user_id),
                'status': 'running',
                'data': json.dumps({
                    'description': unicode(
                         message
                    )}
                )
            }
        )
        self.session.commit()

        return job

    def validate_selection(self, session, entities):
        # The action will not get discovered if this method returns False
        if not entities:
            return False

        entity_type, _ = entities[0]
        if entity_type in VALID_ENTITIES:
            return True
        else:
            return False

    def interface(self, session, entities, event):
        '''Return interface for *entities*.'''
        values = event['data'].get('values', {})
        # Interface will be raised as long as there's no value set.
        # here is a good place where to put validations.
        if values:
            return

        # Populate ui.
        widgets = [
            {
                'label': 'Shared Link(Box)',
                'value': '',
                'data': [],
                'name': 'box_link',
                'type': 'text'
            },
            {
                'label': 'Type',
                'value': '',
                'data': [],
                'name': 'type',
                'type': 'enumerator'
            },
            {
                'label': 'Status',
                'value': '',
                'data': [],
                'name': 'status',
                'type': 'enumerator'
            },
            {
                'label': 'Transfer',
                'value': False,
                'name': 'transfer',
                'type': 'boolean'
            }
        ]

        self.asset_types = session.query(
            "select name from AssetType"
        ).all()
        self.version_statuses = session.query(
            "select name from Status"
        ).all()
        for asset_type in self.asset_types:
            widgets[1]["data"].append(
                {
                    'label': asset_type["name"],
                    'value': asset_type["name"]
                }
            )
        for asset_type in self.asset_types:
            widgets[1]["data"].append(
                {
                    'label': asset_type["name"],
                    'value': asset_type["name"]
                }
            )
        entity_type, entity_id = entities[0]
        schema_statuses = ftrack.getProject(
            session.query(
                "select project.name from {0} where id is '{1}'".format(
                    entity_type, entity_id
                )
            ).one()["project"]["name"]
        ).getVersionStatuses()
        for status_type in schema_statuses:
            widgets[2]["data"].append(
                {
                    'label': status_type.getName(),
                    'value': status_type.getName()
                }
            )

        widgets[1]['value'] = "Upload"
        widgets[2]['value'] = "Not started"

        return widgets

    def discover(self, session, entities, event):

        return self.validate_selection(session, entities)

    def file_transfer(
        self, session, source, destination, asset_type,
        version_status, user_id=None
    ):
        hidden_files = [
            "desktop.ini",
            "thumbs.db",
            ".DS_Store"
        ]
        self.added_component = []

        try:
            for fileItem in os.listdir(source):
                file_location = os.path.join(source, fileItem)
                if os.path.isdir(file_location):
                    # Create New Folders
                    dest_folder = None
                    rootFolder = session.query(
                        'select descendants.id, descendants.name '
                        'from TypedContext where id is {0}'.format(
                            destination['id']
                        )
                    ).one()
                    for rootItem in rootFolder['descendants']:
                        if fileItem == rootItem['name']:
                            dest_folder = session.query(
                                'TypedContext where is is {0}'.format(
                                    rootItem['id']
                                )
                            ).one()
                            break
                    if not dest_folder:
                        dest_folder = session.create('Folder', {
                            'name': fileItem,
                            'parent': destination
                        })
                        session.commit()
                    self.file_transfer(
                        session,
                        file_location,
                        dest_folder,
                        asset_type,
                        version_status,
                        user_id
                    )

                if os.path.isfile(file_location) and fileItem != hidden_files:
                    # Creating new Asset in ftrack server
                    # Note: Existing Asset will version up
                    version = 0
                    try:
                        try:
                            asset = session.query(
                                'select versions from Asset where name '
                                'is "{0}" and context_id is "{1}"'.format(
                                    fileItem, destination['id']
                                )
                            ).one()
                            version = len(asset['versions'])
                        except ftrack_api.exception.NoResultFoundError:
                            self.ftrack_log.info(
                                "Creating new Asset for {0}".format(
                                    fileItem
                                )
                            )
                            asset = None

                        if asset is None:
                            # New Asset Container
                            asset = session.create('Asset', {
                                'name': fileItem,
                                'type': asset_type,
                                'parent': destination
                            })
                        # Adding AssetVersion to empty Asset
                        asset_version = session.create('AssetVersion', {
                            'task': destination,
                            'asset': asset,
                            'name': fileItem,
                            'status': version_status,
                            'version': version
                        })
                        session.commit()

                        # Adding File to empty AssetVersion
                        # enocode_media only works on compatible media file type
                        asset_version.create_component(file_location, data={
                            'name': fileItem
                        }, location='auto')
                        asset_version.encode_media(file_location)
                        self.added_component.append(asset_version)

                    except ftrack_api.exception.LocationError as error:
                        self.ftrack_log.info(
                            'Component {} already in target location'.format(
                                fileItem
                            )
                        )
                        self.ftrack_log.error(error)
                        session.rollback()

                    except ftrack_api.exception.ServerError as error:
                        self.ftrack_log.error(error)
                        session.rollback()
            
            self.job['status'] = 'done'
            session.commit()

        except BaseException:
            self.ftrack_log.exception('Transfer failed')
            session.rollback()
            self.job['status'] = 'failed'
            session.commit()

    def launch(self, session, entities, event):

        '''Return result of running action.'''
        # If no link value is coming from user, bail out
        values = event['data'].get('values', {})
        box_link = values['box_link']
        if not (values and box_link):
            return

        # Create a new running Job.
        self.job = self._create_job(
            event, 'Preparing to check Link...'
        )
        user_id = event['source']['user']['id']

        source = subprocess.check_output(
            [
                "C:/Python27/python.exe",
                os.path.join(
                    os.path.dirname(__file__),
                    'box_file_download.py'
                ),
                box_link,
                os.getenv('temp')
            ]
        )

        asset_type = values['type']
        version_status = values['status']
        transfer = values['transfer']
        entity_type, entity_id = entities[0]
        destination = session.get(entity_type, entity_id)

        # Information gathered through ftrack query
        for item in self.asset_types:
            if item['name'] == asset_type:
                asset_type = item
                break
        for item in self.version_statuses:
            if item['name'] == version_status:
                version_status = item
                break

        self.ftrack_log.info(source.strip())
        self.file_transfer( 
            session,
            source.strip(),
            destination,
            asset_type,
            version_status,
            user_id=user_id
        )

        shutil.rmtree(source, ignore_errors=True)
        # Launch message to diplay on WebUI
        return {
            'success': True,
            'message': 'Successfully retrived items from Box'
        }

def register(api_object, *kwargs):
    '''Register hook with provided *api_object*.'''
    if not isinstance(api_object, ftrack_api.Session):
        # Exit to avoid registering this plugin again.
        return

    action = BoxFtrackTransfer(
        api_object
    )
    action.register()